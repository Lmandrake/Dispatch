"""CSV import of issues.

``parse_issues_csv(text)`` turns CSV text into row dicts for
``Tracker.import_issues``.  The header decides which columns are present;
column names are case-insensitive and surrounding whitespace is ignored.

Accepted columns:

==============  ===============================================
column          meaning
==============  ===============================================
title           required, non-empty
description     free text
type            bug / task / story / chore (default task)
priority        low / normal / high / urgent (default normal)
assignee        a username, or empty
labels          ``;``-separated labels (``,`` also accepted)
due             YYYY-MM-DD, or empty
estimate        an integer, or empty
==============  ===============================================

The columns of an issue *export* that make no sense on import (``key``,
``project``, ``number``, ``status``, ``reporter``, ``watchers``,
``created``, ``updated``, ``closed``) are accepted and ignored, so the CSV
written by ``trellis export issues`` can be imported into another project
as-is.  Any other column is an error, as is a row with the wrong number of
cells.  Empty lines are skipped.
"""

import csv
import io

from trellis.errors import ValidationError

IMPORT_COLUMNS = ("title", "description", "type", "priority", "assignee", "labels", "due", "estimate")
IGNORED_COLUMNS = ("key", "project", "number", "status", "reporter", "watchers",
                   "created", "updated", "closed")


def _split_labels(text):
    text = text.replace(",", ";")
    return [p.strip() for p in text.split(";") if p.strip()]


def parse_issues_csv(text):
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ValidationError("CSV file is empty") from None
    names = [h.strip().lower() for h in header]
    unknown = [n for n in names if n not in IMPORT_COLUMNS and n not in IGNORED_COLUMNS]
    if unknown:
        raise ValidationError(f"unknown CSV column(s): {', '.join(unknown)}")
    if "title" not in names:
        raise ValidationError("CSV needs a title column")
    if len(set(names)) != len(names):
        raise ValidationError("CSV has duplicate columns")
    rows = []
    for line_no, cells in enumerate(reader, start=2):
        if not cells or all(not c.strip() for c in cells):
            continue
        if len(cells) != len(names):
            raise ValidationError(f"line {line_no}: expected {len(names)} cells, got {len(cells)}")
        raw = dict(zip(names, cells))
        row = {}
        for name in IMPORT_COLUMNS:
            if name not in raw:
                continue
            value = raw[name].strip() if name != "description" else raw[name]
            if name == "labels":
                row[name] = _split_labels(value)
            elif name == "estimate":
                row[name] = value or None
            else:
                row[name] = value
        rows.append(row)
    return rows
