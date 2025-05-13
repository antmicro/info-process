# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from .compare import (
    unpack_existing_into_stream_pairs,
    get_coverages_and_descriptions,
    unzip_to_stringio,
)
from .parser import Stream
from zipfile import ZipFile

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument("inputs", type=str, nargs="+", default=[],
                        help="Input archives paths")
    parser.add_argument("--output", type=str, required=True,
                        help="Output archive path")

def copy_file_between_zips(source: ZipFile, destination: ZipFile, file_name: str):
    destination.writestr(file_name, unzip_to_stringio(source, file_name).getvalue())

def drop_lines_not_in_other(this_stream: Stream, other_stream: Stream, this_prefix: str) -> Stream:
    output_coverage_source_files = [x.source_file for x in other_stream.records]
    for record in this_stream.records:
        if record.source_file not in output_coverage_source_files:
            this_stream.records.pop(name)
        elif this_prefix in record.lines_per_prefix:
            record.lines_per_prefix[this_prefix] = [
                line
                for line in record.lines_per_prefix["TEST"]
                if other_stream.has_entries_for_source_file_line(
                    record.source_file, line.split(",")[0]
                )
            ]
    return this_stream

def store_filtered(source_zip: ZipFile, target_zip: ZipFile, desc_path: str, info_path: str, output_streams: Stream):
    if desc_path is None:
        return
    info_base = info_path.removesuffix(".info")
    desc_stream = Stream(source_file_prefix="SN")
    desc_stream.load(unzip_to_stringio(source_zip, desc_path))

    output_stream = output_streams[info_base]
    filtered_stream = drop_lines_not_in_other(desc_stream, output_stream, "TEST")
    target_zip.writestr(desc_path, str(filtered_stream))

def main(args: argparse.Namespace):
    assert len(args.inputs) == 2, "Currently only comparision between 2 files is supported"
    assert all([x.endswith(".zip") for x in args.inputs]), "Only `zip` extension is supported"
    path_this, path_other = args.inputs

    stream_pairs = unpack_existing_into_stream_pairs(path_this, path_other)

    output_streams = {
        name: this.diff(other) for name, (this, other) in stream_pairs.items()
    }

    with ZipFile(path_other, "r") as other_zip, ZipFile(args.output, "w") as out_zip:
        copy_file_between_zips(other_zip, out_zip, "config.json")
        copy_file_between_zips(other_zip, out_zip, "sources.txt")

        coverage_description_pairs = get_coverages_and_descriptions(other_zip)
        for info_path, desc_path in coverage_description_pairs:
            store_filtered(other_zip, out_zip, desc_path, info_path, output_streams)

        for name, stream in output_streams.items():
            info_path = name + ".info"
            out_zip.writestr(info_path, str(stream))
