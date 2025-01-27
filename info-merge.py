#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import handlers
from parser import Stream, Record
import re

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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inputs', type=str, nargs='+', default=[],
                        help='.info files to be merged')
    parser.add_argument('--output', type=str, required=True,
                        help="Output file's path")
    args = parser.parse_args()

    stream = Stream()
    stream.install_category_handler(['BRDA'], merge_brda)
    stream.install_category_handler(['DA'], merge_da)
    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))
    stream.install_category_handler(['TN', 'SF', 'FNF', 'FNH'], squash_misc)

    print(f'Merging input files...')
    for path in args.inputs:
        print(path)
        with open(path, 'rt') as f:
            stream.merge(f)

    print(f'Saving to {args.output}')
    with open(args.output, 'wt') as f:
        stream.save(f)

if __name__ == '__main__':
    main()
