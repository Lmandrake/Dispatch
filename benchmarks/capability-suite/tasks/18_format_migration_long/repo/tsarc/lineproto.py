"""InfluxDB-style line protocol import and export.

One line per row::

    <measurement>[,<tag>=<value>...] <field>=<value>[,<field>=<value>...] <timestamp>

Mapping to a table:

* ``str`` columns become tags, every other value column becomes a field;
  the time column is the timestamp, written in **nanoseconds** (the
  protocol's default precision), so microseconds are multiplied by 1000.
* Field values: floats as ``repr`` (``nan``/``inf`` are not representable in
  the protocol and those fields are left out of the line), ints with an
  ``i`` suffix, bools as ``true``/``false``.
* Tag keys and values, field keys and the measurement escape commas, spaces
  and ``=`` with a backslash.

Import builds a table whose schema is: ``ts:ts``, then one column per field
key (in order of first appearance; type from the first value seen), then one
``str`` column per tag key.  A field missing from a line is an error unless
it is a float field (then NaN); a missing tag is the empty string.
"""
import math
import re

from . import types as T
from .errors import CsvImportError, SchemaError
from .schema import Column, Schema
from .table import Table

_ESC = re.compile(r"([, =\\])")


def _escape(text):
    return _ESC.sub(r"\\\1", text)


def _split_unescaped(text, sep):
    parts = []
    buf = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _split_line(line):
    """Split into the three space-separated sections, honouring escapes and quotes."""
    sections = []
    buf = []
    in_quote = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            buf.append(line[i:i + 2])
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        if ch == " " and not in_quote:
            sections.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    sections.append("".join(buf))
    return [s for s in sections if s != ""]


def _field_text(type_, value):
    if type_ == T.FLOAT:
        if math.isnan(value) or math.isinf(value):
            return None
        return repr(value)
    if type_ == T.INT:
        return f"{value}i"
    if type_ == T.BOOL:
        return "true" if value else "false"
    raise AssertionError(type_)


def table_to_lines(table, measurement):
    schema = table.schema
    tags = [c for c in schema.columns[1:] if c.type == T.STR]
    fields = [c for c in schema.columns[1:] if c.type in (T.INT, T.FLOAT, T.BOOL)]
    if not fields:
        raise SchemaError("line protocol needs at least one int, float or bool column")
    lines = []
    tag_cols = [table.column_view(c.name) for c in tags]
    field_cols = [table.column_view(c.name) for c in fields]
    for i, t in enumerate(table.time_values()):
        head = _escape(measurement)
        for c, col in zip(tags, tag_cols):
            v = col[i]
            if v:
                head += f",{_escape(c.name)}={_escape(v)}"
        parts = []
        for c, col in zip(fields, field_cols):
            v = col[i]
            if v is None:
                continue
            text = _field_text(c.type, v)
            if text is not None:
                parts.append(f"{_escape(c.name)}={text}")
        if not parts:
            continue
        lines.append(f"{head} {','.join(parts)} {t * 1000}")
    return lines


def write_lines(path, table, measurement):
    lines = table_to_lines(table, measurement)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    return len(lines)


def _parse_field(text, lineno):
    if text.endswith("i") and re.fullmatch(r"[+-]?\d+i", text):
        return T.INT, int(text[:-1])
    if text in ("true", "t", "T", "True", "TRUE"):
        return T.BOOL, True
    if text in ("false", "f", "F", "False", "FALSE"):
        return T.BOOL, False
    if text.startswith('"'):
        raise CsvImportError("string fields are not supported", lineno)
    try:
        return T.FLOAT, float(text)
    except ValueError:
        raise CsvImportError(f"bad field value {text!r}", lineno) from None


def lines_to_table(text, measurement=None):
    """Parse line protocol; only lines of ``measurement`` are kept when it is given."""
    rows = []
    field_types = {}
    tag_keys = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sections = _split_line(line)
        if len(sections) != 3:
            raise CsvImportError("expected '<measurement,tags> <fields> <timestamp>'", lineno)
        head, fields_text, ts_text = sections
        head_parts = _split_unescaped(head, ",")
        meas = head_parts[0]
        if measurement is not None and meas != measurement:
            continue
        tags = {}
        for part in head_parts[1:]:
            k, sep, v = part.partition("=")
            if not sep:
                raise CsvImportError(f"bad tag {part!r}", lineno)
            tags[k] = v
            if k not in tag_keys:
                tag_keys.append(k)
        fields = {}
        for part in _split_unescaped(fields_text, ","):
            k, sep, v = part.partition("=")
            if not sep:
                raise CsvImportError(f"bad field {part!r}", lineno)
            ty, val = _parse_field(v, lineno)
            known = field_types.setdefault(k, ty)
            if known != ty:
                if {known, ty} == {T.INT, T.FLOAT}:
                    field_types[k] = T.FLOAT
                else:
                    raise CsvImportError(f"field {k!r} changes type from {known} to {ty}", lineno)
            fields[k] = val
        try:
            ns = int(ts_text)
        except ValueError:
            raise CsvImportError(f"bad timestamp {ts_text!r}", lineno) from None
        rows.append((lineno, ns // 1000, fields, tags))
    names = list(field_types)
    clash = set(names) & set(tag_keys)
    if clash:
        raise CsvImportError(f"names used as both tag and field: {', '.join(sorted(clash))}")
    schema = Schema([Column("ts", T.TS)] + [Column(n, field_types[n]) for n in names] +
                    [Column(k, T.STR) for k in tag_keys])
    table = Table(schema)
    for lineno, ts, fields, tags in rows:
        row = [ts]
        for n in names:
            if n in fields:
                v = fields[n]
                row.append(float(v) if field_types[n] == T.FLOAT else v)
            elif field_types[n] == T.FLOAT:
                row.append(math.nan)
            else:
                raise CsvImportError(f"line has no value for field {n!r}", lineno)
        row.extend(tags.get(k, "") for k in tag_keys)
        table.append(row)
    return table


def read_lines(path, measurement=None):
    with open(path, encoding="utf-8") as fh:
        return lines_to_table(fh.read(), measurement)
