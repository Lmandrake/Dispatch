"""CSV import and export.

Export writes a header row of ``name:type`` specs (the schema text, split by
column) followed by one row per table row, every value in its canonical text
form (:func:`tsarc.types.format_text`).

Import reads such a file back.  The header may also hold bare names; then
the types come from ``schema`` (a :class:`~tsarc.schema.Schema` or schema
text) if given, otherwise they are inferred from the data: a column whose
every value parses as an int is ``int``, else ``float``, else (for the first
column) ``ts``, else ``bool`` (``true``/``false``/``yes``/``no`` only), else
``str``.  The first column is always the time column.
"""
import csv
import io

from . import types as T
from .errors import CsvImportError, SchemaError
from .schema import Column, Schema
from .table import Table


def table_to_csv(table, out, header=True):
    """Write ``table`` as CSV to the text stream ``out``.  Returns the number of rows."""
    w = csv.writer(out, lineterminator="\n")
    schema = table.schema
    if header:
        w.writerow([c.to_text() for c in schema])
    types = [c.type for c in schema]
    n = 0
    for row in table.rows():
        w.writerow([T.format_text(t, v) for t, v in zip(types, row)])
        n += 1
    return n


def table_to_csv_text(table, header=True):
    buf = io.StringIO()
    table_to_csv(table, buf, header=header)
    return buf.getvalue()


def _parse_header(cells):
    names = []
    types = []
    for i, cell in enumerate(cells):
        cell = cell.strip()
        if not cell:
            raise CsvImportError(f"column {i + 1} has an empty header", 1)
        if ":" in cell:
            try:
                col = Column.parse(cell)
            except SchemaError as exc:
                raise CsvImportError(str(exc), 1) from None
            names.append(col.name)
            types.append(col.type)
        else:
            names.append(cell)
            types.append(None)
    return names, types


def _infer(values, first):
    candidates = [T.INT, T.FLOAT] + ([T.TS] if first else []) + [T.BOOL, T.STR]
    if first:
        candidates = [T.TS]
    for t in candidates:
        if all(T.looks_like(t, v) for v in values):
            return t
    return T.STR


def csv_to_table(src, schema=None):
    """Read CSV from a text stream (or a str holding CSV text) and return a Table."""
    if isinstance(src, str):
        src = io.StringIO(src)
    reader = csv.reader(src)
    try:
        header = next(reader)
    except StopIteration:
        raise CsvImportError("empty CSV file (no header row)") from None
    names, types = _parse_header(header)
    rows = []
    for lineno, cells in enumerate(reader, start=2):
        if not cells or (len(cells) == 1 and not cells[0].strip()):
            continue
        if len(cells) != len(names):
            raise CsvImportError(f"expected {len(names)} fields, found {len(cells)}", lineno)
        rows.append((lineno, cells))

    if schema is not None:
        if isinstance(schema, str):
            schema = Schema.parse(schema)
        if schema.names != names:
            raise CsvImportError(f"CSV columns {', '.join(names)} do not match schema "
                                 f"{schema.to_text()}", 1)
        for i, (t, c) in enumerate(zip(types, schema)):
            if t is not None and t != c.type:
                raise CsvImportError(f"column {c.name!r} is {t} in the CSV header but {c.type} in "
                                     f"the schema", 1)
    else:
        resolved = []
        for i, (name, t) in enumerate(zip(names, types)):
            if t is None:
                t = _infer([cells[i] for _, cells in rows], i == 0)
            resolved.append((name, t))
        try:
            schema = Schema([Column(n, t) for n, t in resolved])
        except SchemaError as exc:
            raise CsvImportError(str(exc), 1) from None

    table = Table(schema)
    cols = table._cols
    for lineno, cells in rows:
        parsed = []
        for c, text in zip(schema, cells):
            try:
                parsed.append(T.parse_text(c.type, text))
            except SchemaError as exc:
                raise CsvImportError(f"column {c.name!r}: {exc}", lineno) from None
        for col, v in zip(cols, parsed):
            col.append(v)
    return table


def read_csv_file(path, schema=None):
    with open(path, newline="", encoding="utf-8") as fh:
        return csv_to_table(fh, schema)


def write_csv_file(path, table, header=True):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        return table_to_csv(table, fh, header=header)
