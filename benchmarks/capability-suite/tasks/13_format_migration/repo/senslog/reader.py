"""Reading SLOG files."""
import struct
from pathlib import Path

from . import v1
from .errors import CorruptFileError, UnsupportedVersionError

_PREFIX = struct.Struct("<4sH")


def sniff_version(data):
    """Return the format version of ``data`` (the start of a SLOG file)."""
    if len(data) < _PREFIX.size:
        raise CorruptFileError("file too short")
    magic, version = _PREFIX.unpack_from(data, 0)
    if magic != v1.MAGIC:
        raise CorruptFileError("bad magic number")
    return version


class LogReader:
    """A fully parsed SLOG file.

    Attributes:
        path     -- the path that was read
        version  -- the on-disk format version
        station  -- station name from the header
        created  -- creation time from the header, epoch seconds
        records  -- list of Record, in file order
    """

    def __init__(self, path):
        self.path = Path(path)
        data = self.path.read_bytes()
        self.version = sniff_version(data)
        if self.version == 1:
            self.created, self.station, self.records = v1.decode_file(data)
        else:
            raise UnsupportedVersionError(self.version)

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def sensors(self):
        """Sorted list of distinct sensor ids."""
        return sorted({r.sensor for r in self.records})

    def for_sensor(self, sensor):
        return [r for r in self.records if r.sensor == sensor]

    def between(self, start=None, end=None):
        """Records with start <= timestamp < end (either bound may be None)."""
        out = []
        for r in self.records:
            if start is not None and r.timestamp < start:
                continue
            if end is not None and r.timestamp >= end:
                continue
            out.append(r)
        return out


def open_log(path):
    return LogReader(path)


def read_records(path):
    return list(LogReader(path).records)
