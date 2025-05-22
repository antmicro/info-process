# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from pathlib import Path
import argparse
from .parser import Stream, Record, split_da, split_brda
from . import handlers
import csv


class ExplicitWaivers:
    LINE_NUMBER_WHOLE_FILE_MARKER: int = 0
    GROUP_WHOLE_LINE_MARKER: int = 0

    @dataclass(frozen=True)
    class Exclude:
        line_start: int # the first line of the range to exclude inclusive, zero means to exclude the whole file
        line_end: int # the last line of the range to exclude inclusive, line_start == line_end means exclude a single line, line_start == line_end == 0 means exclude whole file
        group_start: int
        group_end: int

    def __init__(self, path: Path = None) -> None:
        self.excluded: dict[str, list[ExplicitWaivers.Exclude]] = {}

        if path is None:
            # For such case is_excluded always returns False, so no exclusion at all
            return

        def get_or_default(l: list[str], index: int, min_len: int) -> int:
            assert min_len > index, f'{min_len=} has to be greater than {index=}'
            if len(l) >= min_len:
                return int(l[index])
            return 0

        with open(path, newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                file = row[0]
                if file not in self.excluded:
                    self.excluded[file] = list()
                self.excluded[file].append(ExplicitWaivers.Exclude(
                    line_start=get_or_default(row, 1, 3),
                    line_end=get_or_default(row, 2, 3),
                    group_start=get_or_default(row, 3, 5),
                    group_end=get_or_default(row, 4, 5),
                ))

    def is_excluded(self, file: str, line_number: int, group_number: int=-1) -> bool:
        for path, blacklist in self.excluded.items():
            if not file == path:
                # Exclusion list doesn't impact the file
                continue

            for entry in blacklist:
                line_excluded = (entry.line_start == entry.line_end == self.LINE_NUMBER_WHOLE_FILE_MARKER) or \
                    (entry.line_start <= line_number <= entry.line_end)

                group_excluded = group_number < 0 or (entry.group_start == entry.group_end == self.GROUP_WHOLE_LINE_MARKER) or \
                    (entry.group_start <= group_number <= entry.group_end)

                if line_excluded and group_excluded:
                    # Exclusion entry matched
                    return True

        return False

def create_waivers_handler(waivers: ExplicitWaivers):
    def filter_waivers(prefix: str, data: list[str], file: Record) -> list[str]:
        passed = []
        for entry in data:
            if prefix == 'BRDA':
                line, group, _, __ = split_brda(entry)
            elif prefix == 'DA':
                line, _ = split_da(entry)
                group = -1
            if not waivers.is_excluded(file.source_file, line, group):
                passed.append(entry)
        return passed

    return filter_waivers

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('input', type=str,
                        help='Input file in the .info format that should be processed')
    parser.add_argument('--output', type=str,
                        help="Optional output path to save the result to instead of the default which is modifying the input file in-place")
    parser.add_argument('--waivers', type=str, required=True,
                        help="Waivers in CSV format")

def main(args: argparse.Namespace):
    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()

    waivers = ExplicitWaivers(Path(args.waivers))

    stream.install_category_handler(['BRDA', 'DA'], create_waivers_handler(waivers))

    stream.install_category_handler(['BRF'], handlers.create_count_restore('BRDA'))
    stream.install_category_handler(['BRH'], handlers.create_hit_count_restore('BRDA'))
    stream.install_category_handler(['LF'], handlers.create_count_restore('DA'))
    stream.install_category_handler(['LH'], handlers.create_hit_count_restore('DA'))

    with open(args.input, 'rt') as f:
        stream.load(f)

    with open(args.output, 'wt') as f:
        stream.save(f)
