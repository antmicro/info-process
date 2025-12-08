# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import os.path
import io
import json
from typing import Optional
from .pack import get_coverage_description_paired_files
from .parser import Stream, Record
from dataclasses import dataclass
from functools import reduce
from tabulate import tabulate
from zipfile import ZipFile

GREEN_FORMATTING=""
RED_FORMATTING=""
NO_FORMATTING=""


@dataclass
class CoverageCompare:
    """ Represents difference between two coverage files for one metric (line/branch/...) """
    file_name: str

    # `base` or `other` pair can be None if source file is present only in one file.
    base_total: Optional[int]
    other_total: Optional[int]
    base_hits: Optional[int]
    other_hits: Optional[int]

    def __lt__(self, other: 'CoverageCompare') -> bool:
        return self.file_name < other.file_name

    def __add__(self, other: 'CoverageCompare') -> 'CoverageCompare':
        def _add(a: Optional[int], b: Optional[int]) -> Optional[int]:
            if a is None and b is None:
                return None
            else:
                return (a or 0) + (b or 0)

        return CoverageCompare("",
                               _add(self.base_total, other.base_total),
                               _add(self.other_total, other.other_total),
                               _add(self.base_hits, other.base_hits),
                               _add(self.other_hits, other.other_hits))

    def _assert_hits(self):
        assert self.base_hits is not None or self.other_hits is not None, \
            f"Both base_hits and other_hits can't be None, {self.file_name=}"

    def _assert_total(self):
        assert self.base_total is not None or self.other_total is not None, \
            f"Both base_total and other_total can't be None, {self.file_name=}"

    @property
    def total_delta(self) -> Optional[int]:
        if self.base_total is None or self.other_total is None:
            self._assert_total()
            return None
        return self.other_total - self.base_total

    @property
    def hits_delta(self) -> Optional[int]:
        if self.base_hits is None or self.other_hits is None:
            self._assert_hits()
            return None
        return self.other_hits - self.base_hits

    @property
    def base_coverage(self) -> Optional[float]:
        if not self.present_in_base:
            return None
        return self.base_hits / self.base_total * 100 if self.base_total > 0 else 0

    @property
    def other_coverage(self) -> Optional[float]:
        if not self.present_in_other:
            return None
        return self.other_hits / self.other_total * 100 if self.other_total > 0 else 0

    @property
    def coverage_delta(self) -> Optional[float]:
        if self.other_coverage is None or self.base_coverage is None:
            return None
        return self.other_coverage - self.base_coverage

    @property
    def present_in_base(self) -> bool:
        if self.base_total is None or self.base_hits is None:
            assert self.base_total is None and self.base_hits is None, \
                f"Either both or none of {self.base_total=} and {self.base_hits=} must be set, {self.file_name=}"
            return False
        else:
            return True

    @property
    def present_in_other(self) -> bool:
        if self.other_total is None or self.other_hits is None:
            assert self.other_total is None and self.other_hits is None, \
                f"Either both or none of {self.other_total=} and {self.other_hits=} must be set, {self.file_name=}"
            return False
        else:
            return True

    @property
    def present_in_both(self) -> bool:
        return self.present_in_base and self.present_in_other

    @property
    def is_different(self) -> bool:
        assert self.present_in_both, \
            f"CoverageCompare with only base or other can't provide is_different, {self.file_name=}"
        return (self.total_delta != 0 or self.hits_delta != 0)


def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('inputs', type=str, nargs="+", default=[],
                        help='.info files to be compared')
    parser.add_argument('--table', action='store_true',
                        help='Use table in report')
    parser.add_argument('--colour', '--color', action='store_true',
                        help='Use colours in report')
    parser.add_argument('--output-all', action='store_true',
                        help='Add unchanged files to the report')
    parser.add_argument('--markdown', action='store_true',
                        help='Output Markdown table (implies --table)')
    parser.add_argument('--only-summary', action='store_true',
                        help='Output only summary table')

def compare_records(this_records: dict[str, Record], other_records: dict[str, Record]) -> list[CoverageCompare]:
    # Complexity here is caused by line coverage for which "normal" lines only have DA entries
    # but, e.g., lines inside FOR loops have BRDA entries which should be counted instead.
    #
    # Therefore the returned dict contains BRDA entries unless there is a DA entry
    # for a line without BRDA entries.
    def get_entries_per_record(records: dict[str, Record]) -> dict[str, list[str]]:
        result = {}
        for source_file, record in records.items():
            assert source_file not in result, f"Source file duplicated: {source_file}"
            result[source_file] = {}

            entries = record.lines_per_prefix.get('BRDA', [])
            lines_with_brda_entries = set(
                map(lambda brda: int(brda.split(',')[0]), entries)
            )

            lines_with_da_entries: set[int] = set()
            for da_entry in record.lines_per_prefix.get('DA', []):
                line_no = int(da_entry.split(',')[0])
                # DA entries are only added for lines without any BRDA entries.
                if line_no not in lines_with_brda_entries:
                    # It is assumed that there's only one DA entry per line so let's
                    # make sure it's true.
                    assert line_no not in lines_with_da_entries, \
                            f"Multiple DA lines for {line_no} line in {source_file}"
                    lines_with_da_entries.add(line_no)

                    entries.append(da_entry)
            result[source_file] = entries
        return result

    this_records_lines = get_entries_per_record(this_records)
    other_records_lines = get_entries_per_record(other_records)

    assert len(set(this_records_lines.keys()) & set(other_records_lines.keys())) != 0, "\n".join([
        "Files need to have at least one common source file to be comparable",
        f"    this={this_records_lines.keys()}",
        f"    other={other_records_lines.keys()}",
    ])


    def all_and_covered_lines_count(dataset: list[str]) -> tuple[int, int]:
        def is_line_covered(line_entry) -> bool:
            return int(line_entry.split(",")[-1]) > 0
        return len(dataset), sum(1 for l in dataset if is_line_covered(l))

    result = []
    # Add CoverageCompare objects for all source files from the `other` file.
    # Source files without coverage in `this` file will have `base_total` and `base_hits` unset.
    for file_name, other_lines in other_records_lines.items():
        this_lines = this_records_lines.pop(file_name, None)
        base_total, base_hits = all_and_covered_lines_count(this_lines) if this_lines else (None, None)
        other_total, other_hits = all_and_covered_lines_count(other_lines)
        result.append(CoverageCompare(file_name, base_total, other_total, base_hits, other_hits))

    # Let's add CoverageCompare objects for all source files from `this` absent in `other`.
    for file_name, this_lines in this_records_lines.items():
        base_total, base_hits = all_and_covered_lines_count(this_lines)
        other_total, other_hits = (None, None)
        result.append(CoverageCompare(file_name, base_total, other_total, base_hits, other_hits))

    return sorted(result)

def format_delta(value, percentage: bool = False) -> str:
    if value == 0:
        return "--"

    # NOTE: Plus is added for positive delta, minus for negative is in value already.
    prefix_string = f"{GREEN_FORMATTING}+" if value > 0 else RED_FORMATTING
    value_string = f"{value:.2f}%" if percentage else str(value)

    return f"{prefix_string}{value_string}{NO_FORMATTING}"

def prepare_table_data(name: str, comparison: CoverageCompare) -> list[str]:
    return [
        name,
        f"{comparison.other_coverage:.2f}%",
        f"{comparison.other_hits} [{format_delta(comparison.hits_delta)}]",
        f"{comparison.other_total} [{format_delta(comparison.total_delta)}]",
        f"{format_delta(comparison.coverage_delta, percentage=True)}",
    ]

def print_summary(table: bool, markdown: bool, headers: list[str], data: list[list[str]]):
    if table:
        fmt = "github" if markdown else "rounded_grid"
        print(tabulate(data, headers=headers, tablefmt=fmt))
    else:
        # CSV format
        print(','.join(headers))
        for line in data:
            print(','.join(line))

def report_changes(use_table: bool, use_markdown: bool, name: str, stream_this: Stream, stream_other: Stream, print_all_data: bool):
    headers = ["File Name", "Coverage %", "Hit[Δ]", "Total[Δ]", "Coverage Δ %"]
    comparison_data = compare_records(stream_this.records, stream_other.records)

    def should_be_printed(comparison: CoverageCompare) -> bool:
        return print_all_data or comparison.is_different

    data = [
        prepare_table_data(comparison.file_name, comparison)
        for comparison in comparison_data if should_be_printed(comparison)
    ]

    if len(data) == 0:
        return
    print(f"# {name} diff")
    print_summary(use_table, use_markdown, headers, data)

def summary_with_categories(use_table: bool, use_markdown: bool, streams_pairs: dict[str, tuple[Stream, Stream]], categories: list[str]):
    categorized_stats = {key: CoverageCompare("", 0, 0, 0, 0) for key in categories}
    for name, (this, other) in streams_pairs.items():
        if any(matching_categories:=[x for x in categories if x in name]):
            assert len(matching_categories) == 1, f"All Datasets should match only one category! Offending name: {name}; matching categories: {matching_categories}"
            category = matching_categories[0]
            records = compare_records(this.records, other.records)
            categorized_stats[category] += reduce(lambda x,y : x+y, records)
        else:
            raise AssertionError(f"Dataset {name} does not fit to any of the categories: {categories}")

    headers = ["Type", "Coverage %", "Hit[Δ]", "Total[Δ]", "Coverage Δ %"]
    data = [
        prepare_table_data(name, comparison)
        for name, comparison in categorized_stats.items()
    ]

    print_summary(use_table, use_markdown, headers, data)

def extract_file_name(file_path: str) -> str:
    return os.path.splitext(os.path.basename(file_path))[0]

def get_coverages_and_descriptions(zip_file: ZipFile) -> list[tuple[str]]:
    files_in_zip = zip_file.namelist()
    coverages=[f for f in files_in_zip if f.endswith(".info")]
    descriptions=[f for f in files_in_zip if f.endswith(".desc")]
    assert "config.json" in files_in_zip, f"{zip_file.filename} is not a valid archive - does not contain `config.json`"

    config_json = json.load(unzip_to_stringio(zip_file, "config.json"))

    coverage_description_pairs = get_coverage_description_paired_files(config_json,
                                                                       available_coverages=coverages,
                                                                       available_descriptions=descriptions)
    return coverage_description_pairs

def get_coverages_and_descriptions_sets(zip_file: ZipFile) -> tuple[list[str]]:
    coverage_tuple, description_tuple = zip(*get_coverages_and_descriptions(zip_file))
    return set(coverage_tuple), set(description_tuple)


def unzip_to_stringio(zip_file: ZipFile, name: str) -> io.StringIO:
    unzipped = zip_file.read(name).decode('utf-8')
    return io.StringIO(unzipped)

def unpack_existing_into_stream_pairs(path_this, path_other) -> dict[str, tuple[Stream, Stream]]:
    def unzip_to_stream(zip_file: ZipFile, name: str) -> Stream:
        stream = Stream()
        info_io = unzip_to_stringio(zip_file, name)
        stream.load(info_io)
        return stream

    stream_pairs = {}

    with ZipFile(path_this, 'r') as this_zip, ZipFile(path_other, 'r') as other_zip:
        this_datasets, _ = get_coverages_and_descriptions_sets(this_zip)
        other_datasets, _ = get_coverages_and_descriptions_sets(other_zip)
        assert len(this_datasets & other_datasets) > 0, "\n".join([
            "Archives need to have at least one common dataset file to be comparable",
            f"    {this_datasets=}",
            f"    {other_datasets=}",
        ])

        for common_file in this_datasets & other_datasets:
            stream_pairs[extract_file_name(common_file)] = (unzip_to_stream(this_zip, common_file), unzip_to_stream(other_zip, common_file))
        for this_only_file in this_datasets - other_datasets:
            stream_pairs[extract_file_name(this_only_file)] = (unzip_to_stream(this_zip, this_only_file), Stream())
        for other_only_file in other_datasets - this_datasets:
            stream_pairs[extract_file_name(other_only_file)] = (Stream(), unzip_to_stream(other_zip, other_only_file))

    return stream_pairs

def main(args: argparse.Namespace):
    assert len(args.inputs) == 2,  "Currently only comparision between 2 files is supported"

    args.table = args.table or args.markdown

    if args.colour:
        from colorama import init, Fore, Style

        # `strip=False` preserves color even when the output is piped.
        # Stripping doesn't make sense since color is optional.
        init(strip=False)

        global GREEN_FORMATTING
        global NO_FORMATTING
        global RED_FORMATTING

        GREEN_FORMATTING=Fore.GREEN
        NO_FORMATTING=Style.RESET_ALL
        RED_FORMATTING=Fore.RED

    stream_pairs = {}
    path_this, path_other = args.inputs[0], args.inputs[1]
    print(f"Comparing {path_this} against {path_other}")

    def extension_equals(path, expected_extension) -> bool:
        return path.endswith(f".{expected_extension}")

    if all([extension_equals(x, "info") for x in args.inputs]):
        stream_this, stream_other = Stream(), Stream()
        with open(path_this, 'rt') as f_this, open(path_other, 'rt') as f_other:
            stream_this.load(f_this)
            stream_other.load(f_other)
        stream_pairs[f"{extract_file_name(path_this)}..{extract_file_name(path_other)}"] = (stream_this, stream_other)
    elif all([extension_equals(x, "zip") for x in args.inputs]):
        stream_pairs = unpack_existing_into_stream_pairs(path_this, path_other)
    else:
        raise Exception("Wrong files format. Both files must have the same extension. Supported extensions: `info` ,`zip`")

    if not args.only_summary:
        for name in sorted(stream_pairs.keys()):
            this, other = stream_pairs[name]
            report_changes(args.table, args.markdown, name, this, other, args.output_all)
    if len(stream_pairs) > 1:
        print("# Summary")
        summary_with_categories(args.table, args.markdown, stream_pairs, ["line", "branch", "cond", "toggle", "assert", "fsm"])
