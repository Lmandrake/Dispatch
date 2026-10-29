"""Writing SLOG files."""
import time
import zlib
from pathlib import Path

from . import v1


def write_log(path, records, station="", created=None):
    """Write ``records`` to ``path`` as a SLOG file.

    station -- station name stored in the header
    created -- creation time, epoch seconds; defaults to now

    Returns the number of records written.
    """
    records = list(records)
    if created is None:
        created = int(time.time())
    path = Path(path)
    crc = 0
    with path.open("wb") as fh:
        head = v1.encode_header(len(records), created, station)
        fh.write(head)
        crc = zlib.crc32(head, crc)
        for rec in records:
            raw = v1.encode_record(rec)
            fh.write(raw)
            crc = zlib.crc32(raw, crc)
        fh.write(v1.CRC.pack(crc & 0xFFFFFFFF))
    return len(records)
