# info-process

Copyright (c) 2025 [Antmicro](https://www.antmicro.com)

info-process is a tool processing [LCOV](https://github.com/linux-test-project/lcov)'s `.info` format.
Such files can be used in, e.g., [Coverview](https://github.com/antmicro/coverview) which is a tool for generating coverage dashboards.
The overview of the `.info` format is available in LCOV's `geninfo` manual page (`man geninfo`) in the `FILES` section and [online](https://manpages.debian.org/bookworm/lcov/geninfo.1.en.html#FILES).
Tool is aimed at working with coverage reports generated by running hardware simulations, for example in [Verilator](https://github.com/verilator/verilator).

## Installation

The tool can be installed using `pip`:

```bash
pip install git+https://github.com/antmicro/info-process.git
```

## Transforming `.info` files

Various transformations can be made to the provided `.info` files.
By default files are modified in place.
Multiple transformations can be made to the input file by specifying multiple options, described further.

### Adding missing BRDA entries

`BRDA` entries can be added for lines that only contain `DA` entries using the `--add-missing-brda-entries` option.

For example:
```bash
info-process transform --add-missing-brda-entries coverage-toggles.info
```

will modify the `coverage-toggles.info` file in-place like so:
```diff
 DA:30,1
 DA:31,0
 BRDA:30,0,toggle,1
+BRDA:31,0,toggle,0
```

### Duplicating BRDA entries

`BRDA` entries can be duplicated using the `--add-two-way-toggles` option.
Old entries will be replaced by two entries with `_0->1` and `_1->0` suffixes added to their names.

For example:
```bash
info-process transform --add-two-way-toggles coverage-toggles.info
```

will modify the `coverage-toggles.info` file in-place like so:
```diff
-BRDA:30,0,toggle[0],1
+BRDA:30,0,toggle[0]_0->1,1
+BRDA:30,0,toggle[0]_1->0,1
-BRDA:31,0,toggle[1],6
+BRDA:31,0,toggle[1]_0->1,6
+BRDA:31,0,toggle[1]_1->0,6
```

Note that this option will not check if the file already contains duplicated entries.

### Modifying SF entries

Source file paths in `SF` entries (`SF:<PATH>`) can be stripped based on a regular expression provided with the `--strip-file-prefix <REGEX>` option.
Additionally, records for specific source files can be filtered out based on their paths matching a regular expression provided with the `--filter <REGEX>` option.
For non-matching paths you can use `--filter-out <REGEX>`.
Please note that filtering is performed on stripped paths when these two options are used together.

For example, to strip `/root/designs/` prefixes from `SF` entries in a `coverage-toggles.info` file and only keep records for files from the `/root/designs/unit-tests` directory, one can run:

```bash
info-process transform --filter 'unit-tests' --strip-file-prefix '.*/designs/' coverage-toggles.info
```

### Normalizing toggle hit counts

Hit counts greater than 1 in `BRDA` and `DA` entries can be replaced with 1 with the `--normalize-hit-counts` option.

For example:
```bash
info-process transform --normalize-hit-counts coverage-toggles.info
```

will modify the `coverage-toggles.info` file in-place like so:

```diff
 BRDA:30,0,toggle_0,1
-BRDA:30,0,toggle_1,27
+BRDA:30,0,toggle_1,1
 DA:48,0
-DA:49,159
+DA:49,1
```

### Setting block IDs

Block IDs in `BRDA` entries (numbers that are between line number and name) for the same line can be replaced with consecutive numbers.

For example:

```bash
info-process transform --set-block-ids coverage-toggles.info
```

will override the block IDs like so:
```diff
 BRDA:30,0,toggle[0],0
-BRDA:30,0,toggle[1],12
+BRDA:30,1,toggle[1],12
 BRDA:31,0,toggle[2],1
-BRDA:31,0,toggle[3],35
-BRDA:31,0,toggle[4],0
+BRDA:31,1,toggle[3],35
+BRDA:31,2,toggle[4],0
```

Assigned block IDs can be incremented after encountering a configurable amount of matching `BRDA` entries, by additionally using the `--set-block-ids-step <NUMBER>` flag.
For example using `--set-block-ids-step 2` will increment the assigned block ID on every other matching `BRDA` entry like so:
```diff
 BRDA:30,0,toggle[0]_0->1,1
 BRDA:30,0,toggle[0]_1->0,1
-BRDA:30,0,toggle[1]_0->1,1
-BRDA:30,0,toggle[1]_1->0,1
-BRDA:30,0,toggle[2]_0->1,1
-BRDA:30,0,toggle[2]_1->0,1
+BRDA:30,1,toggle[1]_0->1,1
+BRDA:30,1,toggle[1]_1->0,1
+BRDA:30,2,toggle[2]_0->1,1
+BRDA:30,2,toggle[2]_1->0,1
```

## Merging `.info` files

Multiple `.info` files can be merged using the `merge` subcommand, e.g.

```bash
info-process merge --output coverage-merged.info coverage-test1.info coverage-test2.info coverage-test3.info
```

which will merge `coverage-test1.info`, `coverage-test2.info`, `coverage-test3.info` files and save the result to `coverage-merged.info`.

The output file will contain information merged for matching files based on `SF` paths with:
* recalculated `BRF`, `BRH`, `LF` and `LH` entries,
* `DA` entries with total hits for the given line from the input files,
* `BRDA` entries with total hits for the given line and name from the input files and the highest block ID found for the given name in the input files.

`BRDA` entries for the given line will be sorted lexicographically with proper number handling, i.e., id[0], ..., id[9], id[10]...
This might cause block IDs to be out of order in the output file if they were sorted differently in the input files.

To apply this new order to the block IDs of the merged file, one can use `--set-block-ids` option of the `transform` subcommand:
```bash
info-process transform --set-block-ids coverage-merged.info
```

### Test-list file

An additional file with names of tests which provided hits for each line can be optionally created with a `--test-list` option during merging, e.g.:
```bash
info-process merge --test-list test-list.desc --output coverage-merged.info coverage-test1.info coverage-test2.info coverage-test3.info
```

The output file is structured similarly to the `.info` files with the following entries for every source file:
* `SN:<SOURCE_FILE_PATH>`
* `TEST:<LINE>,<TEST_PATH_1>[;<TEST_PATH_2>...]` for each line if there were any hits
* `end_of_record`

#### Test names customization

Test names are constructed from paths of input files with common path prefixes and `.info` suffixes removed by default, e.g., `test1` and `test2` will be used for input files `/ci/test1.info` and `/ci/test2.info`.
Additional strings which should be removed from test names can be provided with a `--test-list-strip <STRING1>[,<STRING2>...]` option.

For example, `coverage-` and `-all.info` can be removed from paths before using them as test names with:
```bash
info-process merge --test-list test-list.desc --test-list-strip coverage-,-all.info --output coverage-merged.info /ci/tests/coverage-*-all.info
```

A common path prefix (`/ci/tests/` in this case) is removed by default and shouldn't be included in the `--test-list-strip` option.
This behavior can be disabled with a `--test-list-full-path` option.
