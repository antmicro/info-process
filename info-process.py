#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from parser import Stream, Record, EntryHandler, RemoveRecord
import re

def two_way_toggle_handler(prefix: str, params: str, file: Record) -> tuple[str, str]:
    # <LINE NUMBER>,<BLOCK>,<NAME>,<HIT COUNT>
    line_number, block, name, hit_count = params.split(',', 3)
    return (
        f'{line_number},{block},{name}_0->1,{hit_count}',
        f'{line_number},{block},{name}_1->0,{hit_count}',
    )

def missing_brda_handler(prefix: str, params: str, file: Record) -> str:
    # <LINE NUMBER>,<HIT COUNT>
    line_number, hit_count = params.split(',', 1)
    if not file.has_entry_for_line('BRDA', line_number):
        file.add('BRDA', f'{line_number},0,toggle,{hit_count}')
    return params

def create_filter_handler(pattern: str, negate: bool = False) -> EntryHandler:
    regex = re.compile(pattern)
    def handler(prefix: str, path: str, file: Record) -> str:
        if negate != (regex.search(path) is not None):
            return path
        raise RemoveRecord()

    return handler

def create_path_strip_handler(pattern: str) -> EntryHandler:
    regex = re.compile(pattern)
    def handler(prefix: str, path: str, file: Record) -> str:
        # Match the pattern from the start and remove what got matched from the path
        if (m := regex.match(path)):
            return path[m.end():]
        return path

    return handler

def normalize_hit_count_handler(prefix: str, params: str, file: Record) -> str:
    if prefix == 'DA':
        line_number, hit_count = params.split(',', 1)
        return f'{line_number},{int(hit_count) > 0:d}'
    elif prefix == 'BRDA':
        line_number, block, name, hit_count = params.split(',', 3)
        return f'{line_number},{block},{name},{int(hit_count) > 0:d}'
    else:
        raise Exception(f'Unsupported prefix: {prefix}')

def set_block_ids_handler(prefix: str, entries: list[str], record: Record):
    result: list[str] = []
    counter = 0
    current_line = -1
    for line in entries:
        line_number, _, name, hit_count = line.split(',', 3)
        # group just based on line numbers
        if current_line != int(line_number):
            counter = -1
            current_line = int(line_number)
        counter += 1
        result.append(f'{line_number},{counter},{name},{hit_count}')

    record.lines_per_prefix[prefix] = result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=str,
                        help='Input file in the .info format that should be processed')
    parser.add_argument('--output', type=str,
                        help='Optional output path to save the result to instead of the default which is modifying the input file in-place')
    parser.add_argument('--add-two-way-toggles', action='store_true', default=False,
                        help='Duplicate BRDA entries in .info files for toggles which have 0->1 and 1->0 toggles combined')
    parser.add_argument('--add-missing-brda-entries', action='store_true', default=False,
                        help='Generate BRDA entries for lines which only have DA entries. ' +
                        'Can be combined with --add-two-way-toggles to get separate entries for each added toggle')
    parser.add_argument('--filter', type=str,
                        help='Only keep entries for files matching the provided regular expression')
    parser.add_argument('--filter-out', type=str,
                        help='Only keep entries for files not matching the provided regular expression. Evaluated after --filter')
    parser.add_argument('--strip-file-prefix', type=str,
                        help='Remove the provided pattern from file paths in SF entries')
    parser.add_argument('--normalize-hit-counts', action='store_true', default=False,
                        help='Replace hit counts greater than 1 in BRDA and DA entries with 1')
    parser.add_argument('--set-block-ids', action='store_true', default=False,
                        help='Replace group number in BRDA with consecutive numbers for entries on the same line')
    args = parser.parse_args()

    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()

    if args.strip_file_prefix is not None:
        stream.install_handler(['SF'], create_path_strip_handler(args.strip_file_prefix))

    if args.filter is not None:
        stream.install_handler(['SF'], create_filter_handler(args.filter))

    if args.filter_out is not None:
        stream.install_handler(['SF'], create_filter_handler(args.filter_out, negate=True))

    if args.set_block_ids:
        stream.install_category_handler('BRDA', set_block_ids_handler)

    if args.add_two_way_toggles:
        stream.install_handler(['BRDA'], two_way_toggle_handler)

    if args.add_missing_brda_entries:
        stream.install_handler(['DA'], missing_brda_handler)

    if args.normalize_hit_counts:
        stream.install_handler(['DA', 'BRDA'], normalize_hit_count_handler)

    with open(args.input, 'rt') as f:
        stream.run(f)

    with open(args.output, 'wt') as f:
        stream.save(f)

if __name__ == '__main__':
    main()
