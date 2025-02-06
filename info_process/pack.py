# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import itertools
import json
import os
from .parser import Stream, Record
import re
import sys
from typing import TypedDict, Optional, Union
from zipfile import ZipFile, ZIP_DEFLATED

Datasets = dict[str, dict[str, Union[str, list[str]]]]

class CoverviewConfig(TypedDict):
    datasets: Datasets

def generate_datasets(coverage_files: list[str], description_files: list[str]) -> Datasets:
    info_pattern = re.compile(r'coverage_(?P<coverage_type>\w+)_(?P<dataset>\w+).info')
    datasets = Datasets()

    # Find .info files
    for path in coverage_files:
        basename = os.path.basename(path)
        m = info_pattern.match(basename)
        if m is None:
            print(f'ERROR: Coverage file does not follow the naming pattern and will not be added toto the datasets: {path}')
            print('Pass configuration file with "datasets" key properly set when packing coverage and description files which don\'t follow the default "coverage_{type}_{dataset}.info" convention')
            sys.exit(1)

        coverage_type = m.group('coverage_type')
        dataset = m.group('dataset')

        if dataset not in datasets:
            datasets[dataset] = {}

        # Find a matching .desc file
        description_basename = f'tests_{coverage_type}_{dataset}.desc'
        for description_path in description_files:
            if os.path.basename(description_path) == description_basename:
                datasets[dataset][coverage_type] = [basename, description_basename]
                break
        else:
            datasets[dataset][coverage_type] = basename
            print(f'WARNING: Coverage file does not have a matching test description file ({description_basename}): {basename}')

    return datasets

# Returns (coverage_files: list[str], description_files: list[str])
def get_coverage_files(config: CoverviewConfig, available_coverages: list[str], available_descriptions: list[str]) -> tuple[list[str], list[str]]:
    coverages: list[str] = []
    descriptions: list[str] = []

    for dataset in config['datasets'].values():
        for file in dataset.values():
            # This may also be a list of strings in cases where a .info file is paired with a .desc file
            if isinstance(file, str):
                coverage_file_basename = file
                description_file_basename = None
            else:
                if file[0].endswith('.info') and file[1].endswith('.desc'):
                    coverage_file_basename = file[0]
                    description_file_basename = file[1]
                elif file[0].endswith('.desc') and file[1].endswith('.info'):
                    description_file_basename = file[0]
                    coverage_file_basename = file[1]
                else:
                    print(f'ERROR: Invalid dataset files: {file}; only pairs of .info and .desc files are allowed')

            for coverage_file in available_coverages:
                if os.path.basename(coverage_file) == coverage_file_basename:
                    coverages.append(coverage_file)
                    break
            else:
                print(f'ERROR: Coverage file not found: {coverage_file_basename}')
                sys.exit(1)

            if description_file_basename is not None:
                for description_file in available_descriptions:
                    if os.path.basename(description_file) == description_file_basename:
                        descriptions.append(description_file)
                        break
                else:
                    print(f'ERROR: Description file not found: {description_file_basename}')
                    sys.exit(1)

    return (coverages, descriptions)

def get_sources(coverage_files: list[str], root: Optional[str]) -> str:
    found_files: set[str] = set()
    def save_path_handler(prefix: str, path: str, record: Record) -> str:
        found_files.add(path)
        return path

    for file_path in coverage_files:
        stream = Stream()
        stream.install_handler(['SF'], save_path_handler)
        with open(file_path, 'rt') as file:
            stream.load(file)

    sources: list[str] = []
    for source_file in sorted(found_files):
        os_path = source_file if root is None else os.path.join(root, source_file)
        try:
            # Use 'rb' to prevent Python from converting '\r\n' into '\n'
            with open(os_path, 'rb') as file:
                sources.append(f'### FILE: {source_file}\n')
                sources.append(file.read().decode('utf-8'))
        except OSError as e:
            print(f'ERROR: Source file could not be opened: {os_path} ({e})')
            sys.exit(1)

    return ''.join(sources)

def prepare_args(parser: argparse.ArgumentParser):
    parser.add_argument('--output', required=True, type=str,
                        help="Output archive's path")
    parser.add_argument('--config', required=True, type=str,
                        help="Path to coverview's .json configuration file")
    parser.add_argument('--coverage-files', nargs='*', default=[],
                        help='Paths to coverage .info files to be included in the archive')
    parser.add_argument('--description-files', nargs='*', default=[],
                        help='Paths to .desc files to be included in the archive')
    parser.add_argument('--sources-root', type=str,
                        help='Optional root directory where files from SF entries can be found; default: current directory')
    parser.add_argument('--extra-files', nargs='*', default=[],
                        help='Additional files to be included in the archive with "datasets" property being optional; ' +
                        'if missing, "datasets" will be generated based on "coverage_{TYPE}_{DATASET}.info" and "tests_{TYPE}_{DATASET}.desc" names ' +
                        'from files provided in --coverage-files and --description-files')

def main(args: argparse.Namespace):
    with open(args.config, 'rt') as f:
        config: CoverviewConfig = json.load(f)

    if 'datasets' not in config:
        print(f'No "datasets" property in {args.config}, it will be generated based on the provided coverage and description files')
        config['datasets'] = generate_datasets(args.coverage_files, args.description_files)
    else:
        print(f'Using "datasets" property from {args.config}')

    used_coverage, used_descriptions = get_coverage_files(config, args.coverage_files, args.description_files)
    sources = get_sources(used_coverage, args.sources_root)

    if os.path.isfile(args.output):
        os.remove(args.output)

    with ZipFile(args.output, 'x', compression=ZIP_DEFLATED) as archive:
        # Write the config
        archive.writestr('config.json', json.dumps(config))

        # Write coverage files and test description files
        for file in itertools.chain(used_coverage, used_descriptions):
            archive.write(file, os.path.basename(file))

        # Write combined sources
        archive.writestr('sources.txt', sources)

        # Write extra files
        for path in args.extra_files:
            archive.write(path, os.path.basename(path))
