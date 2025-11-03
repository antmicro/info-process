# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from dataclasses import dataclass, asdict, field
from io import TextIOWrapper
import json
import os
from .parser import Stream, Record, EntryHandler, split_da, split_brda
from .pack import extract_type_and_dataset, Datasets
from typing import TextIO, Generator, Any, Union, Optional
from zipfile import ZipFile

UNKNOWN_COVERAGE = 'unknown'

@dataclass
class Summary:
    hit: int = field(default=0)
    total: int = field(default=0)

@dataclass
class GroupSummary:
    summary: Summary = field(default_factory=Summary)
    groups: dict[int, dict[str, int]] = field(default_factory=dict)

    def update_summary(self):
        self.summary = Summary()
        for group in self.groups.values():
            self.summary.hit += sum(1 if hit > 0 else 0 for hit in group.values())
            self.summary.total += len(group)

LinesSummary = dict[int, Union[int, GroupSummary]]

@dataclass
class FileSummary:
    summary: Summary = field(default_factory=Summary)
    line_stats: LinesSummary = field(default_factory=dict)

    def update_summary(self):
        self.summary = Summary()
        for line in self.line_stats.values():
            if isinstance(line, int):
                self.summary.hit += 1 if line > 0 else 0
                self.summary.total += 1
            else:
                line.update_summary()
                self.summary.hit += line.summary.hit
                self.summary.total += line.summary.total

@dataclass
class CoverageTypeSummary:
    summary: Summary = field(default_factory=Summary)
    files: dict[str, FileSummary] = field(default_factory=dict)

    def update_summary(self):
        self.total = Summary()
        for file in self.files.values():
            self.summary.hit += file.summary.hit
            self.summary.total += file.summary.total

@dataclass
class Report:
    report: dict[str, dict[str, CoverageTypeSummary]] = field(default_factory=dict)

    def __post_init__(self):
        # Initialize here, so that those fields are not visible to `asdict`
        # (and not serialized with the rest of the report)
        self.current_type: str = UNKNOWN_COVERAGE
        self.current_dataset: str = UNKNOWN_COVERAGE

    def file_summary_for(self, path: str) -> FileSummary:
        if self.current_dataset not in self.report:
            self.report[self.current_dataset] = {}
        if self.current_type not in self.report[self.current_dataset]:
            self.report[self.current_dataset][self.current_type] = CoverageTypeSummary()

        ct = self.report[self.current_dataset][self.current_type]
        if path not in ct.files:
            ct.files[path] = FileSummary()
        return ct.files[path]

    def all_coverage_types(self) -> Generator[CoverageTypeSummary, Any, None]:
        for dataset in self.report:
            for ct in self.report[dataset].values():
                yield ct

    def all_files(self) -> Generator[FileSummary, Any, None]:
        for ct in self.all_coverage_types():
            for file in ct.files.values():
                yield file

    def create_counter(self) -> EntryHandler:
        def counter(prefix: str, params: str, file: Record) -> str:
            line_stats = self.file_summary_for(file.source_file).line_stats
            if prefix == 'DA':
                line_num, hit_count = split_da(params)
                # Note that it's going to be replaced with GroupSummary if there are BRDAs for the same line
                if line_num not in line_stats:
                    line_stats[line_num] = hit_count
                elif isinstance(line_stats[line_num], int):
                    line_stats[line_num] += hit_count
            else:
                line_num, group, name, hit_count = split_brda(params)
                if line_num not in line_stats or not isinstance(line_stats[line_num], GroupSummary):
                    line_stats[line_num] = GroupSummary()

                current_summary: GroupSummary = line_stats[line_num]
                if group not in current_summary.groups:
                    current_summary.groups[group] = {}
                if name not in current_summary.groups[group]:
                    current_summary.groups[group][name] = 0
                current_summary.groups[group][name] += hit_count

            return params

        return counter

    def update_summary(self):
        for file in self.all_files():
            file.update_summary()

        for ct in self.all_coverage_types():
            ct.update_summary()

def extract_type_and_dataset_from_config(path: str, datasets: Optional[Datasets]) -> Optional[tuple[str, str]]:
    if datasets is None:
        # Follow the naming convention if config is not available
        if m := extract_type_and_dataset(os.path.basename(path)):
            return m
        return None

    for dataset in datasets:
        for coverage_type, files in datasets[dataset].items():
            if isinstance(files, str):
                if path == files:
                    return (coverage_type, dataset)
            else:
                for f in files:
                    if path == f:
                        return (coverage_type, dataset)

    return None

def collect_streams(inputs: list[str]) -> Generator[tuple[TextIO, str, str], Any, None]:
    for path in inputs:
        if path.endswith('.info'):
            if info := extract_type_and_dataset(path):
                coverage_type, dataset = info
            else:
                raise ValueError(f"Could not establish dataset and coverage type for input file: {path}")

            yield (open(path, 'rt'), coverage_type, dataset)
        elif path.endswith('.zip'):
            archive = ZipFile(path, 'r')
            try:
                config: Datasets = json.loads(archive.read('config.json'))["datasets"]
            except:
                config = None

            for member in archive.filelist:
                if not member.filename.endswith('.info'):
                    continue

                if info := extract_type_and_dataset_from_config(member.filename, config):
                    coverage_type, dataset = info
                else:
                    raise ValueError(f"Could not establish dataset and coverage type for input file: {member.filename} from archive: {path}")

                yield (
                    TextIOWrapper(archive.open(member, 'r'), encoding='utf-8'), coverage_type, dataset
                )
        else:
            raise ValueError(f'Unknown file type for generating report: {path}')

def filter_key(value: Any, to_remove: str):
    if isinstance(value, dict):
        return {
            key: filter_key(val, to_remove)
            for key, val in value.items()
            if key != to_remove
        }
    else:
        return value

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('input', type=str, nargs='+', default=[],
                        help='Input .info files or .zip archives')
    parser.add_argument('--output', type=str, required=True,
                        help='Location of the generated report')
    parser.add_argument('--pretty-print', action='store_true', default=False,
                        help='Pretty print the report')
    parser.add_argument('--file-summary-only', action='store_true', default=False,
                        help='Generate report containing summaries only for files')

def main(args: argparse.Namespace):
    report = Report()
    stream = Stream()
    stream.install_handler(['DA', 'BRDA'], report.create_counter())

    for in_stream, coverage_type, dataset in collect_streams(args.input):
        try:
            report.current_type = coverage_type
            report.current_dataset = dataset
            stream.load(in_stream)
        finally:
            in_stream.close()

    report.update_summary()

    json_dict = asdict(report)
    if args.file_summary_only:
        json_dict = filter_key(json_dict, "line_stats")

    with open(args.output, 'wt') as out:
        indent = 2 if args.pretty_print else None
        json.dump(json_dict, out, indent=indent)
