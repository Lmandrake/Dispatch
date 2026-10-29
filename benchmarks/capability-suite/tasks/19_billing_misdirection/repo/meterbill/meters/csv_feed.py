"""API-gateway CSV export reader.

The gateway writes RFC 4180 CSV with a header line:

    event_id,customer,metric,quantity,timestamp,note

* ``note`` is free text typed by support engineers and is usually empty.
* Column order may vary between gateway versions; the header is authoritative.
* Rows that do not validate go to the result's ``rejects`` (docs/METERING.md).
"""

from ..timeutil import parse_instant
from .records import FeedResult, UsageRecord, check_quantity

REQUIRED = ("event_id", "customer", "metric", "quantity", "timestamp")


def _unquote(field):
    if len(field) >= 2 and field[0] == '"' and field[-1] == '"':
        return field[1:-1].replace('""', '"')
    return field


def _split_rows(text):
    """Yield (line_number, fields, raw_text) for each line."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        yield lineno, [_unquote(f) for f in line.split(",")], line


def read_csv_feed(text, source="feed.csv"):
    result = FeedResult(source)
    if text.startswith("﻿"):
        text = text[1:]
    header = None
    for lineno, fields, raw in _split_rows(text):
        if fields is None:
            result.reject(lineno, raw)
            continue
        if not fields or all(not f.strip() for f in fields):
            continue
        if header is None:
            header = [f.strip().lower() for f in fields]
            missing = [c for c in REQUIRED if c not in header]
            if missing:
                result.reject(lineno, f"header lacks {', '.join(missing)}", raw)
                return result
            continue
        if len(fields) > len(header):
            continue
        if len(fields) != len(header):
            result.reject(lineno, f"{len(fields)} fields, expected {len(header)}", raw)
            continue
        row = dict(zip(header, (f.strip() for f in fields)))
        try:
            rec = UsageRecord(
                event_id=_need(row, "event_id"),
                customer=_need(row, "customer").upper(),
                metric=_need(row, "metric"),
                quantity=check_quantity(_need(row, "quantity")),
                at=parse_instant(_need(row, "timestamp")),
                source=source,
                line=lineno,
                note=row.get("note", ""),
            )
        except ValueError as e:
            result.reject(lineno, str(e), raw)
            continue
        result.add(rec)
    if header is None:
        result.reject(1, "empty feed")
    return result


def _need(row, key):
    value = row.get(key, "")
    if value == "":
        raise ValueError(f"empty {key}")
    return value
