"""Reading and writing archive files.

The public entry points are :func:`write_archive`, :func:`open_archive` /
:class:`ArchiveReader`, :func:`read_table`, :func:`append_rows`,
:func:`convert` and :class:`ArchiveWriter`.

Supported format versions are listed in :mod:`tsarc.codec`; the reader
detects the version of a file from its header and returns the same API for
every version.
"""
from pathlib import Path

from . import metadata as md
from .codec import DEFAULT_WRITE_VERSION, codec_for
from .codec.sniff import sniff_version
from .errors import QueryError, SchemaError
from .fileutil import atomic_write_bytes, read_bytes
from .schema import Schema
from .table import Table


class ArchiveReader:
    """An archive opened for reading.

    Attributes:
        path      -- the path that was opened
        version   -- on-disk format version
        schema    -- the archive's :class:`~tsarc.schema.Schema`
        metadata  -- ``dict`` of metadata (empty for version 1)
        num_rows  -- number of rows
        size      -- file size in bytes
    """

    def __init__(self, path):
        self.path = Path(path)
        data = read_bytes(self.path)
        self.size = len(data)
        self.version = sniff_version(data)
        codec = codec_for(self.version)
        decoded = codec.decode(data)
        self._table = decoded.table
        self.schema = decoded.table.schema
        self.metadata = dict(decoded.metadata)
        self.num_rows = decoded.table.num_rows

    def __len__(self):
        return self.num_rows

    def __repr__(self):
        return f"ArchiveReader({str(self.path)!r}, version={self.version}, rows={self.num_rows})"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def table(self):
        """The whole archive as a :class:`~tsarc.table.Table`."""
        return self._table

    def column(self, name):
        return self._table.column(name)

    def time_range(self):
        """``(min, max)`` of the time column, or None when the archive has no rows."""
        return self._table.time_range()

    def query(self, start=None, end=None, columns=None, where=None):
        """Rows with ``start <= time < end`` (either bound may be None), in file order.

        ``columns`` limits the result to those columns (the time column is
        always included, first).  ``where`` is a filter expression (see
        :mod:`tsarc.expr`) or a callable taking a row dict.
        """
        if start is not None and end is not None and end < start:
            raise QueryError(f"query end {end} is before start {start}")
        table = self._table
        ts = table.time_values()
        keep = [i for i, t in enumerate(ts)
                if (start is None or t >= start) and (end is None or t < end)]
        result = table.take(keep)
        if where is not None:
            result = _apply_where(result, where)
        if columns is not None:
            result = result.select(columns)
        return result

    def describe(self):
        """Structural facts about the file (used by ``info``)."""
        out = {"version": self.version, "rows": self.num_rows, "columns": len(self.schema),
               "size": self.size}
        return out


def _apply_where(table, where):
    if callable(where):
        mask = [bool(where(r)) for r in table.to_dicts()]
        return table.filter(mask)
    from .expr import compile_expression

    pred = compile_expression(where, table.schema)
    return table.filter(pred.mask(table))


def open_archive(path):
    return ArchiveReader(path)


def read_table(path):
    return ArchiveReader(path).table


def encode_archive(table, metadata=None, version=None):
    """The bytes of an archive holding ``table`` (nothing is written)."""
    if version is None:
        version = DEFAULT_WRITE_VERSION
    codec = codec_for(version)
    return codec.encode(table, md.normalize(metadata))


def write_archive(path, table, metadata=None, version=None):
    """Write ``table`` to ``path`` and return the number of rows written.

    ``version`` defaults to format version 2.  The file is replaced
    atomically: if encoding fails nothing is written and an existing file at
    ``path`` is left as it was.
    """
    if not isinstance(table, Table):
        raise TypeError(f"write_archive needs a Table, got {type(table).__name__}")
    data = encode_archive(table, metadata, version)
    atomic_write_bytes(path, data)
    return table.num_rows


def append_rows(path, table):
    """Append the rows of ``table`` to an existing archive (same schema), keeping its
    format version and metadata.  Returns the new total row count."""
    reader = ArchiveReader(path)
    if table.schema != reader.schema:
        raise SchemaError(f"cannot append rows with schema {table.schema.to_text()} to an archive "
                          f"with schema {reader.schema.to_text()}")
    combined = Table.concat([reader.table, table])
    write_archive(path, combined, reader.metadata, reader.version)
    return combined.num_rows


def convert(src, dst, version):
    """Rewrite ``src`` as format ``version`` at ``dst``; returns the number of rows."""
    reader = ArchiveReader(src)
    return write_archive(dst, reader.table, reader.metadata, version)


def set_metadata(path, set_pairs=(), unset_keys=()):
    """Rewrite an archive with changed metadata (same version and rows)."""
    reader = ArchiveReader(path)
    new = md.updated(reader.metadata, set_pairs, unset_keys)
    write_archive(path, reader.table, new, reader.version)
    return new


class ArchiveWriter:
    """Incremental writer: collect rows, write the archive on :meth:`close`.

    Usage::

        with ArchiveWriter("out.tsa", "ts:ts,temp:float") as w:
            w.write_row((t0, 20.5))
            w.write_table(more)

    Nothing is written if the ``with`` block raises.
    """

    def __init__(self, path, schema, metadata=None, version=None):
        self.path = Path(path)
        self.schema = schema if isinstance(schema, Schema) else Schema.parse(schema) \
            if isinstance(schema, str) else Schema(schema)
        self.metadata = md.normalize(metadata)
        self.version = version
        self._table = Table(self.schema)
        self._closed = False

    def write_row(self, row):
        self._check_open()
        self._table.append(row)

    def write_rows(self, rows):
        for r in rows:
            self.write_row(r)

    def write_table(self, table):
        self._check_open()
        if table.schema != self.schema:
            raise SchemaError(f"table schema {table.schema.to_text()} does not match writer schema "
                              f"{self.schema.to_text()}")
        self._table = Table.concat([self._table, table])

    @property
    def rows_written(self):
        return self._table.num_rows

    def close(self):
        if self._closed:
            return self._table.num_rows
        self._closed = True
        return write_archive(self.path, self._table, self.metadata, self.version)

    def abort(self):
        self._closed = True

    def _check_open(self):
        if self._closed:
            raise ValueError("writer is closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            self.abort()
        return False
