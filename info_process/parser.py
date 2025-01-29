# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

from typing import TextIO, Callable, Iterable, Generator, Any

END_OF_RECORD = 'end_of_record'

EntryHandler = Callable[[str, str, 'Record'], Iterable[str] | str]
CategoryHandler = Callable[[str, list[str], 'Record'], list[str]]

class RemoveRecord(Exception):
    pass

class LineInfo:
    def __init__(self, initial_file: str | None):
        self.test_files: set[str] = set()
        self.add_source(initial_file)

    def add_source(self, test_file: str | None):
        if test_file is not None:
            self.test_files.add(test_file)

def split_entry(entry: str) -> tuple[str, str]:
    prefix, data = entry.split(':', 1)
    return (prefix, data)

class Record:
    def __init__(self, stream: 'Stream'):
        self.stream = stream
        self.source_file: str | None = None
        self.lines_per_prefix: dict[str, list[str]] = {}
        self.line_info: dict[str, dict[int, LineInfo]] = {}
        self.prefix_order: list[str] = []

    def add(self, prefix: str, data: str):
        if prefix in self.stream.handlers:
            for processed in self._run_handlers(self.stream.handlers[prefix], prefix, data):
                self._add_entry(prefix, processed)
        else:
            self._add_entry(prefix, data)

    def has_entry_for_line(self, prefix: str, line: int) -> bool:
        if prefix not in self.line_info:
            return False
        return line in self.line_info[prefix]

    def save(self, stream: TextIO):
        for prefix in self.prefix_order:
            data = self.lines_per_prefix[prefix]
            if prefix in self.stream.category_handlers:
                for handler in self.stream.category_handlers[prefix]:
                    data = handler(prefix, data, self)

            self.lines_per_prefix[prefix] = data
            for line in self.lines_per_prefix[prefix]:
                stream.write(f'{prefix}:{line}\n')
        stream.write(END_OF_RECORD)
        stream.write('\n')

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
                if isinstance(processed, str):
                    transformed.append(processed)
                else:
                    transformed.extend(processed)
            result = transformed
        return result

    def _add_entry(self, prefix: str, data: str):
        if prefix not in self.lines_per_prefix:
            # Order the sections in the same way as in the original file.
            # This is to an attempt to produce the smallest possible diff
            # between two .info files.
            self.prefix_order.append(prefix)
            self.lines_per_prefix[prefix] = []

        self.lines_per_prefix[prefix].append(data)
        self._update_stats(prefix, data, None)

    def _update_stats(self, prefix: str, data: str, test_file: str | None):
        if self.source_file is None and prefix == 'SF':
            self.source_file = data
        elif prefix == 'BRDA' or prefix == 'DA':
            line_number, *_, hit_count = data.split(',')
            line_number = int(line_number)
            if prefix not in self.line_info:
                self.line_info[prefix] = {}

            if hit_count == '0':
                test_file = None
            if line_number not in self.line_info[prefix]:
                self.line_info[prefix][line_number] = LineInfo(test_file)
            else:
                self.line_info[prefix][line_number].add_source(test_file)

class Stream:
    def __init__(self):
        self.handlers: dict[str, list[EntryHandler]] = {}
        self.category_handlers: dict[str, list[CategoryHandler]] = {}
        self.records: list[Record] = []

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

    def load(self, stream: TextIO):
        for record, lines in self._get_record_lines(stream, None):
            try:
                for prefix, data in lines:
                    record.add(prefix, data)
                self.records.append(record)
            except RemoveRecord:
                pass

    def merge(self, stream: TextIO, test_file_path: str):
        for record, lines in self._get_record_lines(stream, test_file_path):
            record = self._get_matching_record(record)
            for prefix, data in lines:
                try:
                    record.add(prefix, data)
                except RemoveRecord:
                    print('Removing records is not supported during merging')
                    raise

    def save(self, out: TextIO):
        for record in self.records:
            record.save(out)

    def _get_record_lines(self, stream: TextIO, test_file: str | None) -> Generator[tuple[Record, list[tuple[str, str]]], Any, None]:
        record = Record(self)
        lines = []
        for line in stream:
            line = line.strip()
            if line.startswith('#'):
                continue # Skip comments
            if line == END_OF_RECORD:
                yield (record, lines)
                lines = []
                record = Record(self)
            else:
                prefix, data = split_entry(line)
                record._update_stats(prefix, data, test_file)
                lines.append((prefix, data))

    def _get_matching_record(self, record: Record) -> Record:
        assert record.source_file is not None, 'Record without a source file encountered'
        for r in self.records:
            if r.source_file == record.source_file:
                r._merge_stats(record)
                return r
        self.records.append(record)
        return record
