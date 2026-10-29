"""JSON Lines export: one JSON object per row.

Timestamps are written as their text form (``2026-03-01T00:00:00Z``); floats
that JSON cannot represent (NaN and the infinities) are written as the
strings ``"nan"``, ``"inf"`` and ``"-inf"``.
"""
import json
import math

from . import types as T
from .timeutil import format_ts


def _json_value(type_, value):
    if type_ == T.TS:
        return format_ts(value)
    if type_ == T.FLOAT:
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return value
    return value


def row_to_json(schema, row):
    obj = {c.name: _json_value(c.type, v) for c, v in zip(schema, row)}
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def table_to_jsonl(table, out):
    n = 0
    for row in table.rows():
        out.write(row_to_json(table.schema, row))
        out.write("\n")
        n += 1
    return n


def write_jsonl_file(path, table):
    with open(path, "w", encoding="utf-8") as fh:
        return table_to_jsonl(table, fh)
