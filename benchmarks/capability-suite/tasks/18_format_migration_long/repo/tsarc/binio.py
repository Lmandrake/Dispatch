"""Little-endian binary reading and writing helpers used by the codecs."""
import struct

from .errors import FormatError

_U8 = struct.Struct("<B")
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_I64 = struct.Struct("<q")
_F64 = struct.Struct("<d")


class ByteWriter:
    """Accumulates bytes; every ``put_*`` method returns ``self`` so calls can be chained."""

    def __init__(self):
        self._buf = bytearray()

    def __len__(self):
        return len(self._buf)

    def getvalue(self):
        return bytes(self._buf)

    def put_bytes(self, data):
        self._buf += data
        return self

    def put_u8(self, v):
        self._buf += _U8.pack(v)
        return self

    def put_u16(self, v):
        self._buf += _U16.pack(v)
        return self

    def put_u32(self, v):
        self._buf += _U32.pack(v)
        return self

    def put_u64(self, v):
        self._buf += _U64.pack(v)
        return self

    def put_i64(self, v):
        self._buf += _I64.pack(v)
        return self

    def put_f64(self, v):
        self._buf += _F64.pack(v)
        return self

    def put_str_u8(self, raw):
        """Length-prefixed (u8) raw bytes."""
        if len(raw) > 0xFF:
            raise ValueError("string longer than 255 bytes")
        return self.put_u8(len(raw)).put_bytes(raw)

    def put_str_u16(self, raw):
        if len(raw) > 0xFFFF:
            raise ValueError("string longer than 65535 bytes")
        return self.put_u16(len(raw)).put_bytes(raw)

    def put_str_u32(self, raw):
        return self.put_u32(len(raw)).put_bytes(raw)


class ByteReader:
    """Reads from a bytes-like object, raising FormatError on truncation.

    ``what`` is used as the prefix of truncation messages, e.g. ``"header"``
    gives ``header: truncated``.
    """

    def __init__(self, data, pos=0, end=None, what="file"):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end
        self.what = what

    @property
    def remaining(self):
        return self.end - self.pos

    def at_end(self):
        return self.pos >= self.end

    def _need(self, n):
        if self.pos + n > self.end:
            raise FormatError(f"{self.what}: truncated")

    def take(self, n):
        self._need(n)
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return bytes(out)

    def _unpack(self, st):
        self._need(st.size)
        (v,) = st.unpack_from(self.data, self.pos)
        self.pos += st.size
        return v

    def u8(self):
        return self._unpack(_U8)

    def u16(self):
        return self._unpack(_U16)

    def u32(self):
        return self._unpack(_U32)

    def u64(self):
        return self._unpack(_U64)

    def i64(self):
        return self._unpack(_I64)

    def f64(self):
        return self._unpack(_F64)

    def str_u8(self):
        return self.take(self.u8())

    def str_u16(self):
        return self.take(self.u16())

    def str_u32(self):
        return self.take(self.u32())


def decode_utf8(raw, what):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise FormatError(f"{what}: invalid UTF-8") from None


def decode_latin1(raw):
    return raw.decode("latin-1")
