# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from . import merge
from . import transform
from . import pack
from . import extract
from . import waive
from . import compare
import sys

TRANSFORM_CMD = 'transform'
MERGE_CMD = 'merge'
PACK_CMD = 'pack'
EXTRACT_CMD = 'extract'
WAIVE_CMD = 'waive'
COMPARE_CMD = 'compare'

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command_name')
    transform.prepare_args(
        subparsers.add_parser(TRANSFORM_CMD,
                              help='Perform transformations on the provided .info file'))
    merge.prepare_args(
        subparsers.add_parser(MERGE_CMD,
                              help='Merge multiple .info files into one'))
    pack.prepare_args(
        subparsers.add_parser(PACK_CMD,
                              help='Pack coverage data into a zip file for viewing in Coverview'))
    extract.prepare_args(
        subparsers.add_parser(EXTRACT_CMD,
                              help='Extract coverage type from a combined .info file into a separate file'))
    waive.prepare_args(
        subparsers.add_parser(WAIVE_CMD,
                              help='Waive entries based on waiver file'))
    compare.prepare_args(
        subparsers.add_parser(COMPARE_CMD,
                              help='Compare two .info or two .zip files'))

    args = parser.parse_args()

    cmd = args.command_name
    if cmd == TRANSFORM_CMD:
        transform.main(args)
    elif cmd == MERGE_CMD:
        merge.main(args)
    elif cmd == PACK_CMD:
        pack.main(args)
    elif cmd == EXTRACT_CMD:
        extract.main(args)
    elif cmd == WAIVE_CMD:
        waive.main(args)
    elif cmd == COMPARE_CMD:
        compare.main(args)
    else:
        print(f'Invalid subcommand: {cmd}')
        sys.exit(1)
