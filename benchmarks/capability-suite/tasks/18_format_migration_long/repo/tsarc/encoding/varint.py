"""Variable-length integers (draft).

These helpers were written while the next format version was being
discussed and are not used by any codec yet.  ``encode_uvarint`` is the usual
little-endian base-128 encoding: seven bits per byte, low groups first, the
high bit set on every byte except the last.
"""
from ..errors import FormatError

_MASK64 = (1 << 64) - 1


def encode_uvarint(n):
    if n < 0:
        raise ValueError("uvarint must be non-negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def decode_uvarint(data, pos):
    """Return ``(value, new_pos)``."""
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise FormatError("varint: truncated")
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result & _MASK64, pos
        shift += 7
        if shift > 63:
            raise FormatError("varint: too long")


def zigzag(n):
    """Map a signed 64-bit integer to an unsigned one (0, -1, 1, -2 ... -> 0, 1, 2, 3 ...)."""
    return ((n << 1) ^ (n >> 63)) & _MASK64


def unzigzag(z):
    return (z >> 1) ^ -(z & 1)
