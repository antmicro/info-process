# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from collections import defaultdict
from .parser import Stream, Record, CategoryHandler, split_da, split_brda
from . import handlers
from typing import Optional

COND_PREFIXES = ['cond']

def create_prefix_filter(allowed: set[str]) -> CategoryHandler:
    def handler(prefix: str, data: list[str], file: Record) -> list[str]:
        if prefix in allowed:
            return data
        return []

    return handler

def install_branch_filters(stream: Stream, prefixes: list[str], filter_out=False):
    # Stores lines containing accepted BRDA entries for each Record.
    # This is later used to filter out DA entries that don't have
    # BRDA entries on the same line.
    brda_lines: dict[Record, set[int]] = defaultdict(set)

    def filter_brda(prefix: str, params: str, file: Record) -> Optional[str]:
        line, _, name, _ = split_brda(params)
        if filter_out != any(name.startswith(p) for p in prefixes):
            brda_lines[file].add(line)
            return params
        return None

    def filter_da(prefix: str, data: list[str], file: Record) -> list[str]:
        return [da for da in data if split_da(da)[0] in brda_lines[file]]

    stream.install_handler(['BRDA'], filter_brda)
    stream.install_category_handler(['DA'], filter_da)
    stream.install_generic_category_handler(create_prefix_filter({'SF', 'DA', 'BRDA'}))

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('input', type=str,
                        help='Input .info file to extract coverage types from')
    parser.add_argument('--output', type=str, required=True,
                        help="Output file's path")
    parser.add_argument('--coverage-type', type=str, choices=['line', 'branch', 'cond'],
                        help='Coverage type to be extracted. ' +
                        f'BRDA entry is considered a "cond" if its name starts with one of the following prefixes: {COND_PREFIXES}. ' +
                        'Otherwise that BRDA entry is considered to be a "branch".')

def main(args: argparse.Namespace):
    stream = Stream()

    if args.coverage_type == 'line':
        stream.install_generic_category_handler(create_prefix_filter({'SF', 'DA'}))
    elif args.coverage_type == 'branch':
        install_branch_filters(stream, COND_PREFIXES, filter_out=True)
    elif args.coverage_type == 'cond':
        install_branch_filters(stream, COND_PREFIXES)
    else:
        raise RuntimeError(f'Extracting coverage type: {args.coverage_type} is currently not supported')

    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))

    with open(args.input, 'rt') as f:
        stream.load(f)

    with open(args.output, 'wt') as f:
        stream.save(f)
