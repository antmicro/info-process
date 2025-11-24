# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from . import handlers
from .parser import Stream, Record, EntryHandler, RemoveRecord, CategoryHandler, split_brda, split_da
import re

def two_way_toggle_handler(prefix: str, entries: list[str], file: Record) -> list[str]:
    result: list[str] = []
    for entry in entries:
        line_number, block, name, hit_count = split_brda(entry)
        result.append(f'{line_number},{block},{name}_0->1,{hit_count}')
        result.append(f'{line_number},{block},{name}_1->0,{hit_count}')
    return result

def missing_brda_handler(prefix: str, params: str, file: Record) -> str:
    line_number, hit_count = split_da(params)
    if not file.has_entry_for_line('BRDA', line_number):
        file.add('BRDA', f'{line_number},0,toggle,{hit_count}')
    return params

def normalize_path(path):
    normalized_components = []
    components = path.split("/")
    for comp in components:
        if comp == ".." and len(normalized_components) > 0:
            normalized_components.pop()
        elif comp not in ["", ".", ".."]:
            normalized_components.append(comp)

    normalized_path = "/" if path.startswith("/") else ""
    normalized_path += "/".join(normalized_components)
    return normalized_path

def normalize_path_handler(prefix: str, path: str, file: Record) -> str:
    normalized_path = normalize_path(path)
    return normalized_path

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
        line_number, hit_count = split_da(params)
        return f'{line_number},{hit_count > 0:d}'
    elif prefix == 'BRDA':
        line_number, block, name, hit_count = split_brda(params)
        return f'{line_number},{block},{name},{hit_count > 0:d}'
    else:
        raise Exception(f'Unsupported prefix: {prefix}')

def create_block_ids_handler(increment: int) -> CategoryHandler:
    if increment <= 0:
        raise ValueError(f'invalid value in "--set-block-ids-step": {increment}, only integers greater than 0 are allowed')

    def handler(prefix: str, entries: list[str], record: Record) -> list[str]:
        result: list[str] = []
        counter = 0
        increment_counter = -1
        current_line = -1
        for line in entries:
            line_number, _, name, hit_count = split_brda(line)
            # group just based on line numbers
            if current_line != line_number:
                counter = 0
                increment_counter = -1
                current_line = line_number

            increment_counter += 1
            if increment_counter == increment:
                increment_counter = 0
                counter += 1

            result.append(f'{line_number},{counter},{name},{hit_count}')
        return result
    return handler

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('input', type=str,
                        help='Input file in the .info format that should be processed')
    parser.add_argument('--output', type=str,
                        help='Optional output path to save the result to instead of the default which is modifying the input file in-place')
    parser.add_argument('--add-two-way-toggles', action='store_true', default=False,
                        help='Duplicate BRDA entries in .info files for toggles which have 0->1 and 1->0 toggles combined')
    parser.add_argument('--add-missing-brda-entries', action='store_true', default=False,
                        help='Generate BRDA entries for lines which only have DA entries. ' +
                        'Can be combined with --add-two-way-toggles to get separate entries for each added toggle')
    parser.add_argument('--filter', type=str, nargs=1, action='extend', default=[],
                        help='Only keep entries for files matching the provided regular expression')
    parser.add_argument('--filter-out', type=str, nargs=1, action='extend', default=[],
                        help='Only keep entries for files not matching the provided regular expression. Evaluated after --filter')
    parser.add_argument('--strip-file-prefix', type=str, nargs=1, action='extend', default=[],
                        help='Remove the provided pattern from file paths in SF entries')
    parser.add_argument('--normalize-hit-counts', action='store_true', default=False,
                        help='Replace hit counts greater than 1 in BRDA and DA entries with 1')
    parser.add_argument('--set-block-ids', action='store_true', default=False,
                        help='Replace group number in BRDA with consecutive numbers for entries on the same line')
    parser.add_argument('--set-block-ids-step', type=int, default=1,
                        help='Block ID will be incremented after encountering the provided amount of matching entries')
    parser.add_argument('--normalize-paths', action='store_true', default=False,
                        help='Compress path in SF entries')

def main(args: argparse.Namespace):
    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()

    if args.normalize_paths:
        stream.install_handler(['SF'], normalize_path_handler)

    for prefix in args.strip_file_prefix:
        stream.install_handler(['SF'], create_path_strip_handler(prefix))

    for filter in args.filter:
        stream.install_handler(['SF'], create_filter_handler(filter))

    for filter_out in args.filter_out:
        stream.install_handler(['SF'], create_filter_handler(filter_out, negate=True))

    if args.set_block_ids:
        stream.install_category_handler(['BRDA'], create_block_ids_handler(args.set_block_ids_step))

    if args.add_two_way_toggles:
        stream.install_category_handler(['BRDA'], two_way_toggle_handler)

    if args.add_missing_brda_entries:
        stream.install_handler(['DA'], missing_brda_handler)

    if args.normalize_hit_counts:
        stream.install_handler(['DA', 'BRDA'], normalize_hit_count_handler)

    # Always fix counts reported in BRF, BRH, LF and LH
    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))

    with open(args.input, 'rt') as f:
        stream.load(f)

    with open(args.output, 'wt') as f:
        stream.save(f)
