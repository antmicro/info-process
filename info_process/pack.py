# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import argparse
import itertools
import json
import os
from .parser import Stream, Record
import re
import shutil
import sys
from typing import TypedDict, Optional, Union, Iterable
from zipfile import ZipFile, ZIP_DEFLATED

Datasets = dict[str, dict[str, Union[str, list[str]]]]

class CoverviewConfig(TypedDict):
    datasets: Datasets

def generate_datasets(coverage_files: list[str], description_files: list[str]) -> Datasets:
    info_pattern = re.compile(r'coverage_(?P<coverage_type>\w+)_(?P<dataset>\w+).info')
    working_datasets = Datasets()

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

        if dataset not in working_datasets:
            working_datasets[dataset] = {}

        # Find a matching .desc file
        description_basename = f'tests_{coverage_type}_{dataset}.desc'
        for description_path in description_files:
            if os.path.basename(description_path) == description_basename:
                working_datasets[dataset][coverage_type] = [basename, description_basename]
                break
        else:
            working_datasets[dataset][coverage_type] = basename
            print(f'WARNING: Coverage file does not have a matching test description file ({description_basename}): {basename}')

    # Convert the collected dataset to a dataset that is sorted in the correct order
    # Note that this relies on the fact that converting a dict to a JSON string puts keys in
    # the same order that keys where added into the dict
    key_order = ['line', 'branch', 'cond', 'toggle']
    final_datasets = Datasets()
    for dataset in working_datasets:
        # Prepare keys, so that they are processed in order `line`, `branch`, `toggle`, everything else lexicographically
        for key in key_order + sorted(set(working_datasets[dataset].keys()) - set(key_order)):
            if key not in working_datasets[dataset]:
                continue

            if dataset not in final_datasets:
                final_datasets[dataset] = {}

            final_datasets[dataset][key] = working_datasets[dataset][key]

    return final_datasets

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

def pack_zip(output: str, config: CoverviewConfig, sources: str, files_to_pack: Iterable[str]):
    # Remove previous archive, if it exists to not mixup any files
    if os.path.isfile(output):
        print(f'Removing previous output archive: {output}')
        os.remove(output)

    with ZipFile(output, 'x', compression=ZIP_DEFLATED) as archive:
        # Write the config
        archive.writestr('config.json', json.dumps(config, indent=2))

        # Write combined sources
        archive.writestr('sources.txt', sources)

        # Copy all files (coverage, description and extra files)
        for file in files_to_pack:
            archive.write(file, os.path.basename(file))

def pack_directory(output: str, config: CoverviewConfig, sources: str, files_to_pack: Iterable[str]):
    # Remove the previous directory, if it exists to not mixup any files
    if os.path.isdir(output):
        print(f'Removing previous output directory: {output}')
        shutil.rmtree(output, ignore_errors=True)
    os.makedirs(output)

    # Write the config
    with open(os.path.join(output, 'config.json'), 'wt') as file:
        file.write(json.dumps(config, indent=2))

    # Write combined sources
    # File is opened as binary to prevent Python from modifying line end characters
    with open(os.path.join(output, 'sources.txt'), 'wb') as file:
        file.write(sources.encode('utf-8'))

    # Copy all files (coverage, description and extra files)
    for file in files_to_pack:
        shutil.copy(file, output)

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

    all_files = itertools.chain(used_coverage, used_descriptions, args.extra_files)
    if args.output.lower().endswith('.zip'):
        print(f'Creating an output .zip archive: {args.output}')
        pack_zip(args.output, config, sources, all_files)
    else:
        print(f'Creating an output directory: {args.output}')
        pack_directory(args.output, config, sources, all_files)
