"""Codec for archive format version 1 (row-oriented).  See docs/FORMAT_v1.md."""
import zlib

from .. import types as T
from ..binio import ByteReader, ByteWriter
from ..errors import ChecksumError, FormatError, NotRepresentableError, SchemaError
from ..schema import Column, Schema
from ..table import Table
from .sniff import MAGIC

VERSION = 1
SUPPORTED_TYPES = (T.TS, T.INT, T.FLOAT, T.STR)
MAX_STR_BYTES = 0xFFFF


def _crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def check_representable(table, metadata):
    """Raise NotRepresentableError for the first thing version 1 cannot store."""
    if metadata:
        raise NotRepresentableError("version 1 archives cannot store metadata")
    for c in table.schema:
        if c.type not in SUPPORTED_TYPES:
            raise NotRepresentableError(f"type {c.type} needs format version 2 or later", column=c.name)
    for c in table.schema:
        if c.type != T.STR:
            continue
        for i, v in enumerate(table.column_view(c.name)):
            try:
                raw = v.encode("latin-1")
            except UnicodeEncodeError:
                raise NotRepresentableError("text is not latin-1 encodable", column=c.name, row=i) from None
            if len(raw) > MAX_STR_BYTES:
                raise NotRepresentableError(f"text longer than {MAX_STR_BYTES} bytes", column=c.name, row=i)


def encode(table, metadata=None):
    check_representable(table, metadata)
    schema = table.schema
    w = ByteWriter()
    w.put_bytes(MAGIC).put_u16(VERSION).put_u16(0)
    w.put_u16(len(schema)).put_u32(table.num_rows)
    for c in schema:
        w.put_u8(T.TYPE_CODES[c.type]).put_str_u8(c.name.encode("ascii"))
    types = [c.type for c in schema]
    for row in table.rows():
        for type_, v in zip(types, row):
            if type_ == T.FLOAT:
                w.put_f64(v)
            elif type_ == T.STR:
                w.put_str_u16(v.encode("latin-1"))
            else:
                w.put_i64(v)
    body = w.getvalue()
    return body + _crc(body).to_bytes(4, "little")


def _read_schema(r):
    count = r.u16()
    row_count = r.u32()
    cols = []
    for i in range(count):
        code = r.u8()
        name_raw = r.str_u8()
        type_ = T.CODE_TYPES.get(code)
        if type_ not in SUPPORTED_TYPES:
            raise FormatError(f"header: column {i} has unknown type code {code}")
        try:
            name = name_raw.decode("ascii")
        except UnicodeDecodeError:
            raise FormatError(f"header: column {i} name is not ASCII") from None
        cols.append((name, type_))
    try:
        schema = Schema([Column(n, t) for n, t in cols])
    except SchemaError as exc:
        raise FormatError(f"header: {exc}") from None
    return schema, row_count


def decode(data):
    from . import DecodedArchive

    if len(data) < 18:
        raise FormatError("header: truncated")
    stored = int.from_bytes(data[-4:], "little")
    if _crc(data[:-4]) != stored:
        raise ChecksumError("checksum mismatch")
    r = ByteReader(data, end=len(data) - 4, what="header")
    r.take(6)
    flags = r.u16()
    if flags:
        raise FormatError(f"header: unknown flags 0x{flags:04x}")
    schema, row_count = _read_schema(r)
    r.what = "rows"
    types = [c.type for c in schema]
    cols = [[] for _ in schema]
    for _ in range(row_count):
        for type_, col in zip(types, cols):
            if type_ == T.FLOAT:
                col.append(r.f64())
            elif type_ == T.STR:
                col.append(r.str_u16().decode("latin-1"))
            else:
                col.append(r.i64())
    if not r.at_end():
        raise FormatError(f"rows: {r.remaining} unexpected bytes after the last row")
    return DecodedArchive(VERSION, Table._trusted(schema, cols), {})


def describe(data):
    r = ByteReader(data, what="header")
    r.take(8)
    schema, row_count = _read_schema(r)
    return {"version": VERSION, "rows": row_count, "columns": len(schema), "size": len(data)}
