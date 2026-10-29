"""Small helpers for the configuration CSV files (customers, subscriptions,
redemptions, credits, receivables, rates).

These files are written by people in spreadsheets, so the reader is lenient
about the things spreadsheets do: a UTF-8 byte-order mark, blank lines,
trailing whitespace, ``#`` comment lines and column order.  It is strict
about the header: every required column must be present.

The metering feeds have their own reader (meters/csv_feed.py) because they
carry per-row error accounting.
"""

import csv
import io

from .errors import ConfigError


def read_rows(text, *, required, optional=(), source=None):
    """Parse CSV ``text`` into a list of (line_number, dict) pairs.

    Values are stripped; missing optional columns read as "".  Unknown columns
    are kept as-is so callers can choose to look at them.
    """
    if text.startswith("﻿"):
        text = text[1:]
    lines = [ln for ln in text.splitlines(keepends=True)]
    # Drop comment lines but keep numbering stable by replacing them.
    cleaned = []
    for ln in lines:
        if ln.lstrip().startswith("#"):
            cleaned.append("\n")
        else:
            cleaned.append(ln)
    reader = csv.reader(io.StringIO("".join(cleaned)))
    header = None
    rows = []
    for row in reader:
        lineno = reader.line_num
        if not row or all(not c.strip() for c in row):
            continue
        if header is None:
            header = [h.strip().lower() for h in row]
            missing = [c for c in required if c not in header]
            if missing:
                raise ConfigError(f"missing column(s) {', '.join(missing)}", source=source)
            dupes = sorted({h for h in header if header.count(h) > 1})
            if dupes:
                raise ConfigError(f"duplicate column(s) {', '.join(dupes)}", source=source)
            continue
        if len(row) > len(header):
            extra = row[len(header):]
            if any(c.strip() for c in extra):
                raise ConfigError(f"line {lineno}: {len(row)} fields, header has {len(header)}", source=source)
            row = row[: len(header)]
        values = {h: (row[i].strip() if i < len(row) else "") for i, h in enumerate(header)}
        for c in optional:
            values.setdefault(c, "")
        for c in required:
            if values.get(c, "") == "":
                raise ConfigError(f"line {lineno}: empty {c}", source=source)
        rows.append((lineno, values))
    if header is None:
        raise ConfigError("empty file", source=source)
    return rows


def write_rows(header, rows):
    """Render rows (sequences) as CSV text with a header and LF line ends."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(row)
    return out.getvalue()
