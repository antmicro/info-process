#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from parser import Stream, Record, EntryHandler, RemoveRecord
import re

def two_way_toggle_handler(params: str, file: Record) -> tuple[str, str]:
    # <LINE NUMBER>,<BLOCK>,<NAME>,<HIT COUNT>
    line_number, block, name, hit_count = params.split(',', 4)
    return (
        f'{line_number},{block},{name}_0->1,{hit_count}',
        f'{line_number},{block},{name}_1->0,{hit_count}',
    )

def missing_brda_handler(params: str, file: Record) -> str:
    # <LINE NUMBER>,<HIT COUNT>
    line_number, hit_count = params.split(',', 2)
    if not file.has_entry_for_line('BRDA', line_number):
        file.add('BRDA', f'{line_number},0,toggle,{hit_count}')
    return params

def create_filter_handler(pattern: str) -> EntryHandler:
    regex = re.compile(pattern)
    def handler(path: str, file: Record) -> str:
        if regex.search(path):
            return path
        raise RemoveRecord()

    return handler

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
    args = parser.parse_args()

    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()

    if args.filter is not None:
        stream.install_handler('SF', create_filter_handler(args.filter))

    if args.add_two_way_toggles:
        stream.install_handler('BRDA', two_way_toggle_handler)

    if args.add_missing_brda_entries:
        stream.install_handler('DA', missing_brda_handler)

    with open(args.input, 'rt') as f:
        stream.run(f)

    with open(args.output, 'wt') as f:
        stream.save(f)

if __name__ == '__main__':
    main()
