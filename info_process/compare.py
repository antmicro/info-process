# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import os.path
import io
import json
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
    """ Represents difference between two coverage files """
    file_name: str
    base_lines: int
    other_lines: int
    base_covered_lines: int
    other_covered_lines: int

    def __lt__(self, other) -> bool:
        return self.file_name < other.file_name

    def __add__(self, other) -> 'CoverageCompare':
        return CoverageCompare("",
                               (self.base_lines + other.base_lines),
                               (self.other_lines + other.other_lines),
                               (self.base_covered_lines + other.base_covered_lines),
                               (self.other_covered_lines + other.other_covered_lines))

    def lines_delta(self) -> int:
        return self.other_lines - self.base_lines

    def covered_lines_delta(self) -> int:
        return self.other_covered_lines - self.base_covered_lines

    def base_coverage(self) -> float:
        return self.base_covered_lines/self.base_lines * 100 if self.base_lines > 0 else 0

    def other_coverage(self) -> float:
        return self.other_covered_lines/self.other_lines * 100 if self.other_lines > 0 else 0

    def coverage_delta(self) -> float:
        return self.other_coverage() - self.base_coverage()

    def is_different(self) -> bool:
        return (self.lines_delta() != 0 or self.covered_lines_delta() != 0)


def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('inputs', type=str, nargs="+", default=[],
                        help='.info files to be compared')
    parser.add_argument('--table', action='store_true',
                        help='Use table in report')
    parser.add_argument('--colour', action='store_true',
                        help='Use colours in report')
    parser.add_argument('--output-all', action='store_true',
                        help='Add unchanged files to the report')
    parser.add_argument('--markdown', action='store_true',
                        help='Output Markdown table (implies --table)')
    parser.add_argument('--only-summary', action='store_true',
                        help='Output only summary table')

def compare_records(this_records: list[Record], other_records: list[Record]) -> list[CoverageCompare]:
    this_records_lines = { source_file: record.lines_per_prefix.get("DA", []) + record.lines_per_prefix.get("BRDA", [])
        for source_file, record in this_records.items() }
    other_records_lines = { source_file: record.lines_per_prefix.get("DA", []) + record.lines_per_prefix.get("BRDA", [])
        for source_file, record in other_records.items() }

    assert len(set(this_records_lines.keys()) & set(other_records_lines.keys())) != 0, "Files need to have at least one common source file to be comparable"

    def all_and_covered_lines_count(dataset: list[str]) -> tuple[int, int]:
        def is_line_covered(line_entry) -> bool:
            return int(line_entry.split(",")[-1]) > 0
        return len(dataset), sum(1 for l in dataset if is_line_covered(l))

    result = []
    # We can discard all files that are present only in the `this_records` - files that have no lines now, have also no coverage
    for file_name, other_lines in other_records_lines.items():
        this_lines, other_lines = this_records_lines.get(file_name, None), other_records_lines[file_name]
        base_lines, base_covered_lines = all_and_covered_lines_count(this_lines) if this_lines else (0,0)
        other_lines, other_covered_lines = all_and_covered_lines_count(other_lines)
        result.append(CoverageCompare(file_name, base_lines, other_lines, base_covered_lines, other_covered_lines))

    return sorted(result)

def format_value(value, format: str, is_delta: bool = True) -> str:
    if value == 0 and not is_delta:
        return "--"
    prefix_string = (
        (
            f"{GREEN_FORMATTING}+"
            if value > 0
            else f"{RED_FORMATTING}" if value < 0 else ""
        )
        if is_delta
        else ""
    )

    return prefix_string + format.format(value) + f"{NO_FORMATTING}"

def prepare_table_data(name: str, comparison: CoverageCompare) -> list[str]:
    return [
        name,
        format_value(comparison.other_coverage(), format="{:.2f}%", is_delta=False),
        str(comparison.other_covered_lines)
        + format_value(comparison.covered_lines_delta(), format="[{}]"),
        str(comparison.other_lines)
        + format_value(comparison.lines_delta(), format="[{}]"),
        format_value(comparison.coverage_delta(), format="{:.2f}%"),
    ]

def print_summary(table: bool, markdown: bool, headers, data):
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
    if not print_all_data:
        comparison_data =  [x for x in comparison_data if x.is_different()]
    data = [
        prepare_table_data(comparison.file_name, comparison)
        for comparison in comparison_data
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
        assert len(this_datasets & other_datasets) > 0,  "Archives need to have at least one common dataset file to be comparable"

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
        init()
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
