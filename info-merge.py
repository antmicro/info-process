#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import handlers
import os.path
from parser import Stream, Record
import re
from typing import TextIO

def merge_brda(prefix: str, entries: list[str], record: Record) -> list[str]:
    NUMBER_FILL_SIZE = 10
    def process_number(x: str) -> str:
        assert len(x) <= NUMBER_FILL_SIZE, f'Number larger than 10^{NUMBER_FILL_SIZE} encountered: {x}'
        return x.zfill(NUMBER_FILL_SIZE)

    SPLIT_REGEX = re.compile('([0-9]+)')
    def sort_key(entry: str) -> tuple[int, str]:
        line_number, _, name, _ = entry.split(',', 3)
        # Expand numbers encountered in names with leading zeros to make lexicographical
        # sorting order them correctly. E.g. `toggle_10_1` will be expanded to
        # `toggle_0000000010_0000000000` ordering it correctly after `toggle_2_0`
        name = ''.join(process_number(x) if x.isnumeric() else x for x in SPLIT_REGEX.split(name))
        return (int(line_number), name)

    result: list[str] = []
    last_line_number = ""
    last_block = 0
    last_name = ""
    last_hit_count = 0
    for entry in sorted(entries, key=sort_key):
        line_number, block, name, hit_count = entry.split(',', 3)
        block = int(block)
        hit_count = int(hit_count)

        # Increase the hit count if this entry is the same as the previous one
        if line_number == last_line_number and name == last_name:
            last_hit_count += hit_count
            last_block = max(last_block, block)
            continue

        result.append(f'{last_line_number},{last_block},{last_name},{last_hit_count}')
        last_line_number = line_number
        last_block = block
        last_name = name
        last_hit_count = hit_count

    # In the loop entries are only added when name/line changes, so the last entry
    # needs to be added explicitly after the loop finishes.
    result.append(f'{last_line_number},{last_block},{last_name},{last_hit_count}')
    # First entry is dropped, as it contains values used to initialize the `last_*` variables
    # and not actual data from any of the records.
    return result[1:]

def merge_da(prefix: str, entries: list[str], record: Record) -> list[str]:
    def sort_key(entry: str) -> int:
        line_number, _ = entry.split(',',  1)
        return int(line_number)

    result: list[str] = []
    last_line_number = ""
    last_hit_count = 0
    for entry in sorted(entries, key=sort_key):
        line_number, hit_count = entry.split(',', 1)
        # Increase the hit count if this entry is the same as the previous one
        if line_number == last_line_number:
            last_hit_count += int(hit_count)
            continue

        result.append(f'{last_line_number},{last_hit_count}')
        last_line_number = line_number
        last_hit_count = int(hit_count)

    # In the loop entries are only added when name/line changes, so the last entry
    # needs to be added explicitly after the loop finishes.
    result.append(f'{last_line_number},{last_hit_count}')
    # First entry is dropped, as it contains values used to initialize the `last_*` variables
    # and not actual data from any of the records.
    return result[1:]

def squash_misc(prefix: str, entries: list[str], record: Record) -> list[str]:
    unique_entries = set(entries)
    assert len(unique_entries), f'Multiple values for prefix "{prefix}" detected: {unique_entries}, merging logic is not working correctly'
    return [entries[0]]

def create_test_list(out: TextIO, stream: Stream):
    out.write('TN:test_coverage\n')
    for record in stream.records:
        merged: dict[int, set[str]] = {}
        for prefix in ['DA', 'BRDA']:
            if prefix not in record.line_info:
                continue

            for line, info in record.line_info[prefix].items():
                if line in merged:
                    merged[line].update(info.test_files)
                else:
                    merged[line] = info.test_files.copy()

        out.write(f'SN:{record.source_file}\n')
        for line in sorted(merged.keys()):
            if len(merged[line]) == 0:
                continue

            out.write(f'TEST:{line},')
            out.write(';'.join(merged[line]))
            out.write('\n')
        out.write('end_of_record\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inputs', type=str, nargs='+', default=[],
                        help='.info files to be merged')
    parser.add_argument('--output', type=str, required=True,
                        help="Output file's path")
    parser.add_argument('--test-list', type=str, default=None,
                        help='Output path for an optional file with names of tests which provided hits for each line during merging')
    parser.add_argument('--test-list-strip', type=str, default='.info',
                        help='Comma-separated set of strings that should be removed from paths before using them in a test list file, e.g., "coverage-,-all.info"; default: ".info"')
    parser.add_argument('--test-list-full-path', type=bool,
                        help='Prevents automatic common prefix removing from paths before using them in a test list file')
    args = parser.parse_args()

    stream = Stream()
    stream.install_category_handler(['BRDA'], merge_brda)
    stream.install_category_handler(['DA'], merge_da)
    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))
    stream.install_category_handler(['TN', 'SF', 'FNF', 'FNH'], squash_misc)

    if args.test_list is not None:
        # os.path.commonpath is used instead of os.path.commonprefix to prevent automatic removal
        # of parts of file names. It doesn't include the final '/' though so we need to add it.
        common_prefix = '' if args.test_list_full_path else os.path.commonpath(args.inputs) + '/'

    print(f'Merging input files...')
    for path in sorted(args.inputs):
        print(path)
        test_name = None
        if args.test_list is not None:
            test_name = path.removeprefix(common_prefix)
            for string in args.test_list_strip.split(','):
                test_name = test_name.replace(string, '')
        with open(path, 'rt') as f:
            stream.merge(f, test_name)

    print(f'Saving merge output in {args.output}')
    with open(args.output, 'wt') as f:
        stream.save(f)

    if args.test_list is not None:
        print(f'Saving test list in {args.test_list}')
        with open(args.test_list, 'wt') as f:
            create_test_list(f, stream)

if __name__ == '__main__':
    main()
