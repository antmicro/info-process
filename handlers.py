# Copyright (c) Antmicro
# SPDX-License-Identifier: Apache-2.0

from parser import CategoryHandler, Record

def create_count_restore(prefix: str) -> CategoryHandler:
    def handler(_: str, entries: list[str], record: Record) -> list[str]:
        count = 0 if prefix not in record.lines_per_prefix else len(record.lines_per_prefix[prefix])
        return [str(count)]
    return handler

def create_hit_count_restore(prefix: str) -> CategoryHandler:
    def handler(_: str, entries: list[str], record: Record) -> list[str]:
        count = 0
        if prefix in record.lines_per_prefix:
            for entry in record.lines_per_prefix[prefix]:
                *_, hit_count = entry.rsplit(',', 1)
                count += 1 if int(hit_count) > 0 else 0
        return [str(count)]
    return handler
