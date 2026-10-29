"""senslog: read and write SLOG sensor-log container files.

See docs/FORMAT.md for the on-disk format.
"""
from .errors import CorruptFileError, SenslogError, UnsupportedVersionError
from .reader import LogReader, open_log, read_records
from .record import Record
from .writer import write_log

__all__ = [
    "CorruptFileError",
    "LogReader",
    "Record",
    "SenslogError",
    "UnsupportedVersionError",
    "open_log",
    "read_records",
    "write_log",
]

__version__ = "1.4.2"
