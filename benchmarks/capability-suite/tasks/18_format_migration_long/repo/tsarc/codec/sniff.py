"""Recognise archive files and their format version."""
import struct

from ..errors import FormatError

MAGIC = b"TSAR"
_PREFIX = struct.Struct("<4sH")


def sniff_version(data):
    """Return the format version stored in the first 6 bytes of ``data``.

    Raises FormatError when the data is too short or the magic is wrong.
    """
    if len(data) < _PREFIX.size:
        raise FormatError("file too short to be an archive")
    magic, version = _PREFIX.unpack_from(data, 0)
    if magic != MAGIC:
        raise FormatError(f"not an archive (bad magic {bytes(magic)!r})")
    return version


def is_archive(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(_PREFIX.size)
        sniff_version(head)
    except (OSError, FormatError):
        return False
    return True
