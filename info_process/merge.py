# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from . import handlers
from .parser import Stream, Record, split_brda, split_da, EntryHandler
import os.path
import re
from typing import TextIO, Optional, Union

def create_merge_da_handler() -> EntryHandler:
    cache: dict[tuple[Record, int], int] = {}
    def handler(prefix: str, params: str, record: Record) -> Optional[str]:
        own_line_number, own_hit_count = split_da(params)
        cache_key = (record, own_line_number)
        lines = record.lines_per_prefix.get(prefix, [])

        if cache_key not in cache:
            cache[cache_key] = len(lines)
            return params

        entry_number = cache[cache_key]
        line_number, hit_count = split_da(lines[entry_number])
        assert line_number == own_line_number

        lines[entry_number] = f'{own_line_number},{own_hit_count + hit_count}'
        return None

    return handler

def create_merge_brda_handler() -> EntryHandler:
    cache: dict[tuple[Record, int, str], int] = {}
    def handler(prefix: str, params: str, record: Record) -> Optional[str]:
        own_line_number, own_block, own_name, own_hit_count = split_brda(params)
        cache_key = (record, own_line_number, own_name)
        lines = record.lines_per_prefix.get(prefix, [])

        if cache_key not in cache:
            cache[cache_key] = len(lines)
            return params

        entry_number = cache[cache_key]
        line_number, block, name, hit_count = split_brda(lines[entry_number])
        assert line_number == own_line_number
        assert name == own_name

        lines[entry_number] = f'{own_line_number},{max(block, own_block)},{own_name},{own_hit_count + hit_count}'
        return None

    return handler

def sort_da(prefix: str, entries: list[str], record: Record) -> list[str]:
    def key(value: str) -> int:
        line_number, _ = split_da(value)
        return line_number
    entries.sort(key=key)
    return entries

def sort_brda(prefix: str, entries: list[str], record: Record) -> list[str]:
    def key(value: str) -> tuple[int, int]:
        line_number, block, _, _ = split_brda(value)
        return (line_number, block)
    entries.sort(key=key)
    return entries

def sort_brda_names(prefix: str, entries: list[str], record: Record) -> list[str]:
    def convert(value: str) -> str:
        FILL_SIZE = 20
        if value.isdigit():
            assert len(value) <= FILL_SIZE, f'Number larger than 10^{FILL_SIZE} encountered'
            # Expand numbers encountered in names with leading zeros to make lexicographical
            # sorting order them correctly. E.g. `toggle_10_1` will be expanded to
            # `toggle_0000000010_0000000000` ordering it correctly after `toggle_2_0`
            return value.zfill(FILL_SIZE)
        else:
            return value

    SPLIT_REGEX = re.compile('([0-9]+)')
    def key(value: str) -> tuple[int, list[Union[str, int]]]:
        line_number, _, name, _ = split_brda(value)
        name = ''.join(convert(x) for x in SPLIT_REGEX.split(name))
        return (line_number, name)

    entries.sort(key=key)
    return entries

def squash_misc(prefix: str, entries: list[str], record: Record) -> list[str]:
    unique_entries = set(entries)
    assert len(unique_entries), f'Multiple values for prefix "{prefix}" detected: {unique_entries}, merging logic is not working correctly'
    return [entries[0]]

def create_test_list(out: TextIO, stream: Stream):
    out.write('TN:test_coverage\n')
    for record in stream.records.values():
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
            out.write(';'.join(sorted(merged[line])))
            out.write('\n')
        out.write('end_of_record\n')
    
def strip_test_name_regex(test_name, pattern):
    regex = re.compile(pattern)

    def repl(match: re.Match) -> str:
        groups = match.groups()

        if not any(groups):
            return ""

        out = match.group(0)
        for g in groups:
            if g is not None:
                out = out.replace(g, "")
        return out

    return regex.sub(repl, test_name)


def strip_test_name_simple(test_name, pattern):
    for string in pattern.split(','):
            test_name = test_name.replace(string, '')
    return test_name

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('inputs', type=str, nargs='+', default=[],
                        help='.info files to be merged')
    parser.add_argument('--output', type=str, required=True,
                        help="Output file's path")
    parser.add_argument('--test-list', type=str, default=None,
                        help='Output path for an optional file with names of tests which provided hits for each line during merging')
    parser.add_argument(
        "--test-list-strip",
        type=str,
        default=".info",
        help=(
            "Remove pattern from paths before using them in a test list file."
            "In 'simple' mode patterns are treated as a comma-separated list of literal substrings "
            '"(e.g. ".info",coverage-,-all.info"). '
            "In 'regex' mode patterns are interpreted as regular expressions and "
            "if a match contains no capturing groups, the entire match is removed; "
            "if capturing groups are present, only the text matched by those groups is removed "
            '(e.g r".info|_(\d+_)" transforms "./unique_123_reg.info" into "./unique_reg"). '
            "Each sub-string of a path is tried to be matched only once and the leftmost sub-string is matched first, "
            'for example "ab" pattern will convert "aaabbb" to "aabb" and "_._" pattern will convert "a_b_c_d_e" to "ace"'
        )
    )
    parser.add_argument(
        "--test-list-strip-mode",
        choices=["simple", "regex"],
        default="simple",
        help=(
            "Controls how patterns given in --test-list-strip are interpreted. "
            "(see --test-list-strip description)"
        )
    )
    parser.add_argument('--test-list-full-path', type=bool,
                        help='Prevents automatic common prefix removing from paths before using them in a test list file')
    parser.add_argument('--sort-brda-names', action='store_true', default=False,
                        help='Sort BRDA entries using their names')

def main(args: argparse.Namespace):
    stream = Stream()

    # NOTE: All regular handlers for `BRDA` and `DA` entries
    # should be placed BEFORE those two, as they make assumptions
    # about the order and amount of entries!!!
    stream.install_handler(['BRDA'], create_merge_brda_handler())
    stream.install_handler(['DA'], create_merge_da_handler())

    stream.install_category_handler(['BRDA'], sort_brda_names if args.sort_brda_names else sort_brda)
    stream.install_category_handler(['DA'], sort_da)
    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))
    stream.install_category_handler(['SF', 'FNF', 'FNH'], squash_misc)

    if args.test_list is not None:
        # os.path.commonpath is used instead of os.path.commonprefix to prevent automatic removal
        # of parts of file names. It doesn't include the final '/' though so we need to add it.
        common_prefix = '' if args.test_list_full_path else os.path.commonpath(args.inputs) + '/'

    strip_test_name = \
        strip_test_name_simple if args.test_list_strip_mode == "simple" \
        else strip_test_name_regex
    
    print('Merging input files...')
    for path in sorted(args.inputs):
        print(path)
        test_name = None
        if args.test_list is not None:
            test_name = path.removeprefix(common_prefix)
            test_name = strip_test_name(test_name,args.test_list_strip)
        with open(path, 'rt') as f:
            stream.merge(f, test_name)

    print(f'Saving merge output in {args.output}')
    with open(args.output, 'wt') as f:
        stream.save(f)

    if args.test_list is not None:
        print(f'Saving test list in {args.test_list}')
        with open(args.test_list, 'wt') as f:
            create_test_list(f, stream)
