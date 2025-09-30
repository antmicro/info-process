# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

import itertools
from typing import TextIO, Callable, Iterable, Generator, Any, Union, Optional

END_OF_RECORD = 'end_of_record'

# Returning `None` causes the processed entry to be removed from the record
EntryHandler = Callable[[str, str, 'Record'], Union[Iterable[str], str, None]]
CategoryHandler = Callable[[str, list[str], 'Record'], list[str]]

class RemoveRecord(Exception):
    pass

class LineInfo:
    def __init__(self, initial_file: Optional[str]):
        self.test_files: set[str] = set()
        self.add_source(initial_file)

    def add_source(self, test_file: Optional[str]):
        if test_file is not None:
            self.test_files.add(test_file)

def split_entry(entry: str) -> tuple[str, str]:
    prefix, data = entry.split(':', 1)
    return (prefix, data)

def split_da(entry: str) -> tuple[int, int]:
    line_number, hit_count = entry.split(',', 1)

    line_number = int(line_number)
    assert line_number >= 0

    hit_count = int(hit_count)
    assert hit_count >= 0

    return line_number, hit_count

def split_brda(entry: str) -> tuple[int, int, str, int]:
    line_number, block, name, hit_count = entry.split(',', 3)

    line_number = int(line_number)
    assert line_number >= 0

    block = int(block)
    assert block >= 0

    hit_count = int(hit_count)
    assert hit_count >= 0

    return line_number, block, name, hit_count

def split_test(entry: str) -> tuple[int, list[str]]:
    line_number, tests = entry.split(',', 1)

    line_number = int(line_number)
    assert line_number >= 0

    return line_number, tests.split(';')

def get_line_number_and_hit_count(entry: str) -> tuple[int, int]:
    line_number, *_, hit_count = entry.split(',')

    line_number = int(line_number)
    assert line_number >= 0

    hit_count = int(hit_count)
    assert hit_count >= 0

    return line_number, hit_count

def match_second_entries_by(first, second):
    result_dict = {}
    for name in second.keys():
        result_dict[name] = (first.get(name, None), second.get(name))

    return result_dict

def match_second_prefix_entries_by(first: 'Record', second: 'Record', prefix: str, key) -> dict[str, tuple[str]]:
    if second is None or any([prefix not in x.lines_per_prefix for x in (first, second)]):
        return {}

    result_dict = {}
    first_entries = {key(entry): entry for entry in first.lines_per_prefix[prefix]}
    second_entries = {key(entry): entry for entry in second.lines_per_prefix[prefix]}

    for name in second_entries.keys():
        result_dict[name] = (first_entries.get(name, None), second_entries.get(name))

    return result_dict

class Record:
    def __init__(self, stream: 'Stream'):
        self.stream = stream
        self.source_file: Optional[str] = None
        self.lines_per_prefix: dict[str, list[str]] = {}
        self.line_info: dict[str, dict[int, LineInfo]] = {}
        self.prefix_order: list[str] = []
        self.source_file_prefix = self.stream.source_file_prefix

    def diff(self, other: 'Record') -> 'Record':
        # diff entries:
        #  in_old & in_new &  old_hit == new_hit -> skip line
        #  in_old & in_new &  old_hit & !new_hit -> set visited to 0
        #  in_old & in_new & !old_hit &  new_hit -> set visited to 1
        # !in_old & in_new                       -> set visited to new_hit
        #          !in_new                       -> skip line
        assert other is not None, "Should never diff against None"

        class CoverageLine:
            def __init__(self, line: str):
                assert line is not None
                base_string, hit_count = line.rsplit(',', 1)
                self.line_hit = int(hit_count) > 0
                self.base = base_string

            @classmethod
            def instance_or_none(cls, line: str):
                if line is None:
                    return None
                return cls(line)

            def __repr__(self) -> str:
                return f"{self.base},{int(self.line_hit)}"

        def keep_line(values: tuple[CoverageLine, CoverageLine]) -> bool:
            old_line, new_line = values
            if not old_line:
                return True
            return old_line.line_hit != new_line.line_hit

        def new_value(values: tuple[CoverageLine]) -> str:
            """ Asserts that lines have same bases, and retuns new_value. This assumes that lines are not equal"""
            old_line, new_line = values

            if old_line is not None:
                assert old_line.base == new_line.base, "Cannot diff between different lines"
            return str(new_line)

        def match_coverage_lines_by(first: 'Record', second: 'Record', prefix: str, key) -> dict[str, tuple[CoverageLine]]:
            source = match_second_prefix_entries_by(first, second, prefix, key)
            return { k: (CoverageLine.instance_or_none(old), CoverageLine.instance_or_none(new)) for k, (old, new) in source.items()}

        def generate_new_lines_from(first: 'Record', second: 'Record', prefix: str) -> list[str]:
            if prefix not in other.lines_per_prefix:
                return []
            else:
                return [ new_value(values)
                         for _, values
                         in match_coverage_lines_by(first, second, prefix, key=lambda x: x.split(",")[0]).items()
                         if keep_line(values)
                ]

        other.lines_per_prefix["DA"] = generate_new_lines_from(self, other, "DA")
        other.lines_per_prefix["BRDA"] = generate_new_lines_from(self, other, "BRDA")

        return other

    def add(self, prefix: str, data: str):
        if prefix in self.stream.handlers:
            processed = self._run_handlers(self.stream.handlers[prefix], prefix, data)
            if processed is None:
                return

            for entry in processed:
                self._add_entry(prefix, entry)
        else:
            self._add_entry(prefix, data)

    def has_entries_for_line_number(self, line_number: str):
        ret_val = any(line.startswith(f'{line_number},') for line in itertools.chain(*list(self.lines_per_prefix.values())))
        return ret_val

    def has_entry_for_line(self, prefix: str, line: int) -> bool:
        assert type(line) is int
        if prefix not in self.line_info:
            return False
        return line in self.line_info[prefix]

    def save(self, stream: TextIO):
        stream.write(str(self))

    def __str__(self) -> str:
        output: str = ""
        for prefix in self.prefix_order:
            data = self.lines_per_prefix[prefix]
            if prefix in self.stream.category_handlers:
                handlers = itertools.chain(self.stream.category_handlers[prefix], self.stream.generic_category_handlers)
            else:
                handlers = self.stream.generic_category_handlers

            for handler in handlers:
                data = handler(prefix, data, self)

            self.lines_per_prefix[prefix] = data
            output += "\n".join(f'{prefix}:{line}' for line in self.lines_per_prefix[prefix])
            if len(self.lines_per_prefix[prefix]) > 0:
                output += "\n"
        output += f'{END_OF_RECORD}'
        return output

    def _merge_stats(self, other: 'Record'):
        for prefix in other.line_info:
            if prefix not in self.line_info:
                self.line_info[prefix] = other.line_info[prefix]
                continue

            for line, info in other.line_info[prefix].items():
                if line not in self.line_info[prefix]:
                    self.line_info[prefix][line]  = info
                    continue

                self.line_info[prefix][line].test_files.update(info.test_files)

    def _run_handlers(self, handlers: list[EntryHandler], prefix: str, data: str):
        # Run all of the available handler for each of the provided data
        # Since handlers can return multiple values to duplicate entries,
        # the next handler has to be run on the full list of outputs
        # from the previous handler.
        result = [data]
        for handler in handlers:
            transformed = []
            for x in result:
                processed = handler(prefix, x, self)
                if processed is None:
                    return None
                if isinstance(processed, str):
                    transformed.append(processed)
                else:
                    transformed.extend(processed)
            result = transformed
        return result

    def _ensure_prefix(self, prefix: str):
        if prefix not in self.lines_per_prefix:
            # Order the sections in the same way as in the original file.
            # This is to an attempt to produce the smallest possible diff
            # between two .info files.
            self.prefix_order.append(prefix)
            self.lines_per_prefix[prefix] = []

    def _add_entry(self, prefix: str, data: str):
        self._ensure_prefix(prefix)
        self.lines_per_prefix[prefix].append(data)
        self._update_stats(prefix, data, None)

    def _update_stats(self, prefix: str, data: str, test_file: Optional[str]):
        if self.source_file is None and prefix == self.source_file_prefix:
            self.source_file = data
        elif prefix == 'BRDA' or prefix == 'DA':
            line_number, hit_count = get_line_number_and_hit_count(data)
            if prefix not in self.line_info:
                self.line_info[prefix] = {}

            if hit_count == 0:
                test_file = None
            if line_number not in self.line_info[prefix]:
                self.line_info[prefix][line_number] = LineInfo(test_file)
            else:
                self.line_info[prefix][line_number].add_source(test_file)

class Stream:
    def __init__(self, source_file_prefix: str="SF"):
        self.handlers: dict[str, list[EntryHandler]] = {}
        self.category_handlers: dict[str, list[CategoryHandler]] = {}
        self.generic_category_handlers: list[CategoryHandler] = []
        self.records: dict[str, Record] = {}
        self.test_name: str = None
        self.source_file_prefix = source_file_prefix

    def diff(self, other_stream: 'Stream') -> 'Stream':
        this_records, other_records = self.records, other_stream.records
        paired_records = match_second_entries_by(this_records, other_records)
        diffed_records: dict[Record] = {}
        for name, records in paired_records.items():
            this, other = records
            if this is not None:
                diffed_records[name] = this.diff(other)
            elif other is not None:
                diffed_records[name] = other

        other_stream.records = diffed_records
        return other_stream

    def install_handler(self, prefixes: Iterable[str], handler: EntryHandler):
        for prefix in prefixes:
            if prefix not in self.handlers:
                self.handlers[prefix] = [handler]
            else:
                self.handlers[prefix].append(handler)

    def install_category_handler(self, prefixes: Iterable[str], handler: CategoryHandler):
        for prefix in prefixes:
            if prefix not in self.category_handlers:
                self.category_handlers[prefix] = [handler]
            else:
                self.category_handlers[prefix].append(handler)

    def install_generic_category_handler(self, handler: CategoryHandler):
        self.generic_category_handlers.append(handler)

    def load(self, stream: TextIO):
        # Use a list to store all records here as it is likely that some of them will have
        # duplicated source files (e.g. due to prefix stripping)
        record_list: list[Record] = []
        for record, lines in self._get_record_lines(stream, None):
            try:
                for prefix, data in lines:
                    record.add(prefix, data)
                record_list.append(record)
            except RemoveRecord:
                pass

        # Convert the list to the record dict, by concatenating lines for
        # records with a matching source file
        for record in record_list:
            if duplicate := self.records.get(record.source_file):
                for prefix, lines in record.lines_per_prefix.items():
                    duplicate._ensure_prefix(prefix)
                    duplicate.lines_per_prefix[prefix].extend(lines)
            else:
                self.records[record.source_file] = record

    def merge(self, stream: TextIO, test_file_path: str):
        for record, lines in self._get_record_lines(stream, test_file_path):
            record = self._get_matching_record(record)
            for prefix, data in lines:
                try:
                    record.add(prefix, data)
                except RemoveRecord:
                    print('Removing records is not supported during merging')
                    raise

    def has_entries_for_source_file_line(self, source_file_name: str, line_number: str) -> bool:
        record = self.records.get(source_file_name, None)
        if record is None:
            return False
        return record.has_entries_for_line_number(line_number)

    def save(self, out: TextIO):
        out.write(str(self))

    def __str__(self) -> str:
        output: str = ""
        output += f"TN:{self.test_name or ''}\n"
        output += "\n".join(str(record) for record in self.records.values())
        return output + '\n'

    def _get_record_lines(self, stream: TextIO, test_file: Optional[str]) -> Generator[tuple[Record, list[tuple[str, str]]], Any, None]:
        record = Record(self)
        lines = []
        test_name = None  # This is per merged file, self.test_name is one for the output file.
        for line in stream:
            line = line.strip()
            if line.startswith('#'):
                continue # Skip comments
            if line.startswith('TN:'):
                if test_name:
                    print("WARNING: Multiple TN entries found")
                test_name = line.removeprefix('TN:')

                if self.test_name is None:
                    self.test_name = test_name
                elif test_name != self.test_name:
                    print(f"WARNING: Different TN entry: {test_name}, first TN found was: {self.test_name}")
                continue
            if line == END_OF_RECORD:
                yield (record, lines)
                lines = []
                record = Record(self)
            else:
                prefix, data = split_entry(line)
                record._update_stats(prefix, data, test_file)
                lines.append((prefix, data))

        if test_name is None:
            print("WARNING: Missing TN entry")

    def _get_matching_record(self, record: Record) -> Record:
        assert record.source_file is not None, 'Record without a source file encountered'
        if rec:=self.records.get(record.source_file, None):
            rec._merge_stats(record)
            return rec
        self.records[record.source_file] = record
        return record
