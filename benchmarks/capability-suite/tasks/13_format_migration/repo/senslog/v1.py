"""Codec for SLOG format version 1.  See docs/FORMAT.md."""
import struct
import zlib

from .errors import CorruptFileError
from .record import Record

MAGIC = b"SLOG"
VERSION = 1

HEADER = struct.Struct("<4sHHII16s")
RECORD = struct.Struct("<HBBIQ24s")
CRC = struct.Struct("<I")

HEADER_SIZE = HEADER.size  # 32
RECORD_SIZE = RECORD.size  # 40
CRC_SIZE = CRC.size  # 4

STATION_WIDTH = 16
LABEL_WIDTH = 24

KIND_INT = 0
KIND_FLOAT = 1

FLAG_CALIBRATED = 0x01
KNOWN_FLAGS = FLAG_CALIBRATED

U32_MAX = 2 ** 32 - 1

_I64 = struct.Struct("<q")
_F64 = struct.Struct("<d")


def _pack_text(text, width, what):
    if "\x00" in text:
        raise ValueError(f"{what} may not contain NUL characters")
    try:
        raw = text.encode("latin-1")
    except UnicodeEncodeError:
        raise ValueError(f"{what} is not latin-1 encodable: {text!r}") from None
    if len(raw) > width:
        raise ValueError(f"{what} longer than {width} bytes: {text!r}")
    return raw.ljust(width, b"\x00")


def _unpack_text(raw):
    return raw.rstrip(b"\x00").decode("latin-1")


def encode_header(record_count, created, station):
    if not 0 <= created <= U32_MAX:
        raise ValueError(f"created time out of range: {created}")
    return HEADER.pack(
        MAGIC, VERSION, 0, record_count, created, _pack_text(station, STATION_WIDTH, "station")
    )


def decode_header(data):
    """Return (record_count, created, station) from the first HEADER_SIZE bytes."""
    if len(data) < HEADER_SIZE:
        raise CorruptFileError("file too short for a header")
    magic, version, flags, count, created, station = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise CorruptFileError("bad magic number")
    if version != VERSION:
        raise CorruptFileError(f"not a version 1 file (version {version})")
    if flags != 0:
        raise CorruptFileError(f"unknown header flags 0x{flags:04x}")
    return count, created, _unpack_text(station)


def encode_record(rec):
    if not 0 <= rec.timestamp <= U32_MAX:
        raise ValueError(f"timestamp out of range for version 1: {rec.timestamp}")
    flags = FLAG_CALIBRATED if rec.calibrated else 0
    if rec.is_float:
        kind = KIND_FLOAT
        raw_value = _F64.pack(rec.value)
    else:
        kind = KIND_INT
        raw_value = _I64.pack(rec.value)
    (value_bits,) = struct.unpack("<Q", raw_value)
    return RECORD.pack(
        rec.sensor, kind, flags, rec.timestamp, value_bits, _pack_text(rec.label, LABEL_WIDTH, "label")
    )


def decode_record(data, offset, index):
    sensor, kind, flags, timestamp, value_bits, label = RECORD.unpack_from(data, offset)
    raw_value = struct.pack("<Q", value_bits)
    if kind == KIND_INT:
        (value,) = _I64.unpack(raw_value)
    elif kind == KIND_FLOAT:
        (value,) = _F64.unpack(raw_value)
    else:
        raise CorruptFileError(f"record {index}: unknown value kind {kind}", record_index=index)
    if flags & ~KNOWN_FLAGS:
        raise CorruptFileError(f"record {index}: unknown flags 0x{flags:02x}", record_index=index)
    return Record(
        sensor=sensor,
        timestamp=timestamp,
        value=value,
        label=_unpack_text(label),
        calibrated=bool(flags & FLAG_CALIBRATED),
    )


def checksum(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def decode_file(data):
    """Parse a complete v1 file.  Returns (created, station, records)."""
    count, created, station = decode_header(data)
    expected = HEADER_SIZE + count * RECORD_SIZE + CRC_SIZE
    if len(data) != expected:
        raise CorruptFileError(
            f"file length {len(data)} does not match header ({count} records, {expected} bytes)"
        )
    body = data[:-CRC_SIZE]
    (stored,) = CRC.unpack_from(data, len(data) - CRC_SIZE)
    if checksum(body) != stored:
        raise CorruptFileError("checksum mismatch")
    records = []
    for i in range(count):
        records.append(decode_record(data, HEADER_SIZE + i * RECORD_SIZE, i))
    return created, station, records
