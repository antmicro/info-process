# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

from typing import TextIO, Callable, Iterable

END_OF_RECORD = 'end_of_record'

FieldHandler = Callable[[str, 'Record'], Iterable[str]]

def split_entry(entry: str) -> tuple[str, str]:
    prefix, data, *_ = entry.split(':')
    return (prefix, data)

class Record:
    def __init__(self, stream: 'Stream', init: list[str]):
        self.stream = stream
        self.lines_per_prefix: dict[str, list[str]] = {}
        self.prefix_to_line: dict[str, set[int]] = {}
        self.prefix_order: list[str] = []

        for entry in init:
            self._update_stats(*split_entry(entry))

    def add(self, prefix: str, data: str):        
        if prefix in self.stream.handlers:
            transformed_data = self.stream.handlers[prefix](data, self)
            for transformed in transformed_data:
                self._add_entry(prefix, transformed)
        else:
            self._add_entry(prefix, data)

    def has_entry_for_line(self, prefix: str, line: int) -> bool:
        if prefix not in self.prefix_to_line:
            return False
        return line in self.prefix_to_line[prefix]

    def save(self, stream: TextIO):
        for prefix in self.prefix_order:
            for line in self.lines_per_prefix[prefix]:
                stream.write(f'{prefix}:{line}\n')
        stream.write(END_OF_RECORD)
        stream.write('\n')

    def _add_entry(self, prefix: str, data: str):
        if prefix not in self.lines_per_prefix:
            # Order the sections in the same way as in the original file.
            # This is to an attempt to produce the smallest possible diff
            # between two .info files.
            self.prefix_order.append(prefix)
            self.lines_per_prefix[prefix] = []

        self.lines_per_prefix[prefix].append(data)
        self._update_stats(prefix, data)

    def _update_stats(self, prefix: str, data: str):
        if prefix == 'BRDA' or prefix == 'DA':
            line_number, *_ = data.split(',', 2)
            if prefix not in self.prefix_to_line:
                self.prefix_to_line[prefix] = set()
            self.prefix_to_line[prefix].add(line_number)

class Stream:
    def __init__(self):
        self.handlers: dict[str, FieldHandler] = {}
        self.files: list[Record] = []

    def install_handler(self, prefix: str, handler: FieldHandler):
        assert prefix not in self.handlers, f'Handler for prefix "{prefix}" is already installed'
        self.handlers[prefix] = handler

    def run(self, stream: TextIO) -> bool:
        lines = []
        for line in stream:
            line = line.strip()
            if line.startswith('#'):
                # Skip comments
                continue
            if line == END_OF_RECORD:
                self.files.append(self._lines_to_record(lines))
                lines = []
            else:
                lines.append(line)

    def save(self, out: TextIO):
        for file in self.files:
            file.save(out)
    
    def _lines_to_record(self, lines: list[str]) -> Record:
        file = Record(self, lines)
        for line in lines:
            file.add(*split_entry(line))
        return file
