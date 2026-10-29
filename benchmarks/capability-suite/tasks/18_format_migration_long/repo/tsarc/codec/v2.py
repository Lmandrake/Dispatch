"""Codec for archive format version 2 (columnar, one block per column).
See docs/FORMAT_v2.md."""
import zlib

from .. import types as T
from ..binio import ByteReader, ByteWriter, decode_utf8
from ..encoding.bitmap import pack_bits, unpack_bits
from ..errors import ChecksumError, FormatError, NotRepresentableError, SchemaError
from ..schema import Column, Schema
from ..table import Table
from .sniff import MAGIC

VERSION = 2
END_MAGIC = b"RAST"
MAX_META_BYTES = 0xFFFF


def _crc(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def check_representable(table, metadata):
    for key, value in (metadata or {}).items():
        for part, what in ((key, "key"), (value, "value")):
            if len(part.encode("utf-8")) > MAX_META_BYTES:
                raise NotRepresentableError(f"metadata {what} longer than {MAX_META_BYTES} bytes")


def _encode_column(type_, values):
    w = ByteWriter()
    if type_ in (T.TS, T.INT):
        for v in values:
            w.put_i64(v)
    elif type_ == T.FLOAT:
        for v in values:
            w.put_f64(v)
    elif type_ == T.STR:
        blobs = [v.encode("utf-8") for v in values]
        end = 0
        for b in blobs:
            end += len(b)
            w.put_u32(end)
        for b in blobs:
            w.put_bytes(b)
    elif type_ == T.BOOL:
        w.put_bytes(pack_bits(values))
    return w.getvalue()


def encode(table, metadata=None):
    metadata = dict(metadata or {})
    check_representable(table, metadata)
    w = ByteWriter()
    w.put_bytes(MAGIC).put_u16(VERSION).put_u16(0)
    w.put_u32(table.num_rows).put_u16(len(table.schema))
    w.put_u16(len(metadata))
    for key, value in metadata.items():
        w.put_str_u16(key.encode("utf-8")).put_str_u16(value.encode("utf-8"))
    header = w.getvalue()
    w.put_u32(_crc(header))
    for c in table.schema:
        data = _encode_column(c.type, table.column_view(c.name))
        w.put_u8(T.TYPE_CODES[c.type]).put_str_u8(c.name.encode("ascii"))
        w.put_u32(len(data)).put_bytes(data).put_u32(_crc(data))
    w.put_bytes(END_MAGIC)
    return w.getvalue()


def _decode_column(type_, data, rows, name):
    what = f"column '{name}'"
    r = ByteReader(data, what=what)
    if type_ in (T.TS, T.INT, T.FLOAT):
        if len(data) != 8 * rows:
            raise FormatError(f"{what}: expected {8 * rows} bytes, found {len(data)}")
        read = r.f64 if type_ == T.FLOAT else r.i64
        return [read() for _ in range(rows)]
    if type_ == T.STR:
        ends = [r.u32() for _ in range(rows)]
        start = r.pos
        out = []
        prev = 0
        for i, end in enumerate(ends):
            if end < prev or start + end > len(data):
                raise FormatError(f"{what}: bad string offset at row {i}")
            out.append(decode_utf8(bytes(data[start + prev:start + end]), what))
            prev = end
        if start + prev != len(data):
            raise FormatError(f"{what}: unexpected bytes after the last string")
        return out
    if type_ == T.BOOL:
        return unpack_bits(bytes(data), rows, what)
    raise FormatError(f"{what}: unknown type")


def _read_header(data):
    r = ByteReader(data, what="header")
    r.take(6)
    flags = r.u16()
    row_count = r.u32()
    col_count = r.u16()
    meta_count = r.u16()
    metadata = {}
    for _ in range(meta_count):
        key = decode_utf8(r.str_u16(), "header")
        metadata[key] = decode_utf8(r.str_u16(), "header")
    end = r.pos
    stored = r.u32()
    if _crc(bytes(data[:end])) != stored:
        raise ChecksumError("header: checksum mismatch")
    if flags:
        raise FormatError(f"header: unknown flags 0x{flags:04x}")
    return r, row_count, col_count, metadata


def decode(data):
    from . import DecodedArchive

    r, row_count, col_count, metadata = _read_header(data)
    cols = []
    values = []
    for i in range(col_count):
        r.what = f"column {i}"
        code = r.u8()
        name = decode_utf8(r.str_u8(), f"column {i}")
        type_ = T.CODE_TYPES.get(code)
        if type_ is None:
            raise FormatError(f"column {i}: unknown type code {code}")
        size = r.u32()
        block = r.take(size)
        if _crc(block) != r.u32():
            raise ChecksumError(f"column '{name}': checksum mismatch")
        cols.append((name, type_))
        values.append(_decode_column(type_, block, row_count, name))
    r.what = "trailer"
    if r.take(4) != END_MAGIC:
        raise FormatError("trailer: bad end magic")
    if not r.at_end():
        raise FormatError("trailer: unexpected bytes after the end magic")
    try:
        schema = Schema([Column(n, t) for n, t in cols])
    except SchemaError as exc:
        raise FormatError(f"header: {exc}") from None
    return DecodedArchive(VERSION, Table._trusted(schema, values), metadata)


def describe(data):
    r, row_count, col_count, metadata = _read_header(data)
    return {"version": VERSION, "rows": row_count, "columns": col_count, "size": len(data)}
