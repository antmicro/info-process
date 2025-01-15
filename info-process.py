#!/usr/bin/env python3

# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
from parser import Stream

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=str)
    parser.add_argument("--output", type=str)
    args = parser.parse_args()

    # Default to a in-place modification if no output path is specified
    if args.output is None:
        args.output = args.input

    stream = Stream()
    with open(args.input, "rt") as f:
        stream.run(f)

    with open(args.output, "wt") as f:
        stream.save(f)

if __name__ == '__main__':
    main()
