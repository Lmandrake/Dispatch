"""Bit packing for boolean columns.

Format version 2 stores a boolean column as a packed bitmap, **most
significant bit first**: value ``i`` lives in byte ``i // 8`` at bit
``7 - i % 8``.  Unused bits of the last byte are zero.
"""
from ..errors import FormatError


def pack_bits(values):
    out = bytearray((len(values) + 7) // 8)
    for i, v in enumerate(values):
        if v:
            out[i >> 3] |= 0x80 >> (i & 7)
    return bytes(out)


def unpack_bits(data, count, what="bitmap"):
    need = (count + 7) // 8
    if len(data) != need:
        raise FormatError(f"{what}: expected {need} bytes, found {len(data)}")
    values = [bool(data[i >> 3] & (0x80 >> (i & 7))) for i in range(count)]
    if count % 8:
        pad_mask = 0xFF >> (count % 8)
        if data[-1] & pad_mask:
            raise FormatError(f"{what}: non-zero padding bits")
    return values


def packed_size(count):
    return (count + 7) // 8
