#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from parser import Stream, Record

def two_way_toggle_handler(params: str, file: Record) -> tuple[str]:
    # <LINE NUMBER>,<BLOCK>,<NAME>,<HIT COUNT>
    line_number, block, name, hit_count = params.split(',', 4)
    return (
        f'{line_number},{block},{name}_0->1,{hit_count}',
        f'{line_number},{block},{name}_1->0,{hit_count}',
    )

def missing_brda_handler(params: str, file: Record) -> tuple[str]:
    # <LINE NUMBER>,<HIT COUNT>
    line_number, hit_count = params.split(',', 2)
    if not file.has_entry_for_line('BRDA', line_number):
        file.add('BRDA', f'{line_number},0,toggle,{hit_count}')
    return (params,)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=str)
    parser.add_argument("--output", type=str)
    parser.add_argument('--add-two-way-toggles', action='store_true', default=False)
    parser.add_argument('--add-missing-brda-entries', action='store_true', default=False)
    args = parser.parse_args()

    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()
    if args.add_two_way_toggles:
        stream.install_handler("BRDA", two_way_toggle_handler)

    if args.add_missing_brda_entries:
        stream.install_handler("DA", missing_brda_handler)

    with open(args.input, "rt") as f:
        stream.run(f)

    with open(args.output, "wt") as f:
        stream.save(f)

if __name__ == '__main__':
    main()
