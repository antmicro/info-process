# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from pathlib import Path
import argparse
from collections import defaultdict
from .parser import Stream, Record, CategoryHandler, split_da, split_brda
from . import handlers
from typing import Optional
import csv


class ExplicitWaivers:
    LINE_NUMBER_WHOLE_FILE_MARKER: int = 0

    @dataclass(frozen=True)
    class Exclude:
        line_start: int # the first line of the range to exclude inclusive, zero means to exclude the whole file
        line_end: int # the last line of the range to exclude inclusive, line_start == line_end means exclude a single line, line_start == line_end == 0 means exclude whole file

    def __init__(self, path: Path = None) -> None:
        self.excluded: dict[str, list[ExplicitWaivers.Exclude]] = {}

        if path is None:
            # For such case is_excluded always returns False, so no exclusion at all
            return

        with open(path, newline='') as f:
            reader = csv.reader(f)
            for row in reader:
                file = row[0]
                if file not in self.excluded:
                    self.excluded[file] = list()
                self.excluded[file].append(ExplicitWaivers.Exclude(int(row[1]), int(row[2])))

    def is_excluded(self, file: str, line_number: int) -> bool:
        for path, blacklist in self.excluded.items():
            if not file == path:
                # Exclusion list doesn't impact the file
                continue

            for entry in blacklist:
                if (entry.line_start == entry.line_end == self.LINE_NUMBER_WHOLE_FILE_MARKER) or (entry.line_start <= line_number and line_number <= entry.line_end ):
                    # Exclusion entry matched
                    return True

        return False

def create_waivers_handler(waivers: ExplicitWaivers):
    def filter_waivers(prefix: str, data: list[str], file: Record) -> list[str]:
        passed = []
        for entry in data:
            if prefix == 'BRDA':
                line_number, _, __, ___ = split_brda(entry)
            elif prefix == 'DA':
                line_number, _ = split_da(entry)
            if not waivers.is_excluded(file.source_file, line_number):
                passed.append(entry)
        return passed

    return filter_waivers

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('input', type=str,
                        help='Input .info file to extract coverage types from')
    parser.add_argument('--output', type=str, required=True,
                        help="Output file's path")
    parser.add_argument('--waivers', type=str, required=True, help="Waivers yaml")

def main(args: argparse.Namespace):
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
