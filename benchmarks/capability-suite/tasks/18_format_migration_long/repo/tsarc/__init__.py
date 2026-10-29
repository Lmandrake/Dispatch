"""tsarc: columnar time-series archives.

Quick start::

    from tsarc import Schema, Table, write_archive, open_archive

    schema = Schema.parse("ts:ts,temp:float,site:str")
    t = Table.from_rows(schema, [(1_700_000_000_000_000, 21.5, "roof")])
    write_archive("data.tsa", t)
    rd = open_archive("data.tsa")
    rd.query(start=..., end=...)
"""
from .archive import (ArchiveReader, ArchiveWriter, append_rows, convert, encode_archive,
                      open_archive, read_table, set_metadata, write_archive)
from .errors import (ChecksumError, CsvImportError, ExpressionError, FormatError,
                     NotRepresentableError, QueryError, SchemaError, TsarcError,
                     UnsupportedVersionError)
from .schema import Column, Schema
from .table import Table

__version__ = "2.4.0"

__all__ = [
    "ArchiveReader", "ArchiveWriter", "append_rows", "convert", "encode_archive", "open_archive",
    "read_table", "set_metadata", "write_archive",
    "ChecksumError", "CsvImportError", "ExpressionError", "FormatError", "NotRepresentableError",
    "QueryError", "SchemaError", "TsarcError", "UnsupportedVersionError",
    "Column", "Schema", "Table",
]
