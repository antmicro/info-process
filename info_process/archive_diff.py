# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import io
import sys
from .compare import (
    unpack_existing_into_stream_pairs,
    get_coverages_and_descriptions,
    unzip_to_stringio,
)
from .parser import Record
from zipfile import ZipFile

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument("inputs", type=str, nargs="+", default=[],
                        help="Input archives paths")
    parser.add_argument("--output", type=str, required=True,
                        help="Output archive path")

def copy_file_between_zips(source: ZipFile, destination: ZipFile, file_name: str):
    destination.writestr(file_name, unzip_to_stringio(source, file_name).getvalue())

def main(args: argparse.Namespace):
    assert len(args.inputs) == 2, "Currently only comparision between 2 files is supported"
    assert all([x.endswith(".zip") for x in args.inputs]), "Only `zip` extension is supported"
    path_this, path_other = args.inputs

    stream_pairs = unpack_existing_into_stream_pairs(path_this, path_other)

    output_streams = {
        name: this.diff(other) for name, (this, other) in stream_pairs.items()
    }

    with ZipFile(path_this, "r") as other_zip, ZipFile(args.output, "w") as out_file:
        _, other_descriptions = get_coverages_and_descriptions(other_zip)
        copy_file_between_zips(other_zip, out_file, "config.json")
        copy_file_between_zips(other_zip, out_file, "sources.txt")
        for desc in other_descriptions:
            copy_file_between_zips(other_zip, out_file, desc)

        for name, stream in output_streams.items():
            info_content = str(stream)
            out_file.writestr(name + ".info", info_content)
