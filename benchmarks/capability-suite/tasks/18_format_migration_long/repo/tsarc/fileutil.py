"""File helpers: atomic replacement and path handling."""
import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path, data):
    """Write ``data`` to ``path`` atomically.

    The bytes go to a temporary file in the same directory which then
    replaces ``path``; if anything fails the temporary file is removed and an
    existing file at ``path`` is left untouched.
    """
    path = Path(path)
    directory = path.parent if str(path.parent) else Path(".")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_bytes(path):
    return Path(path).read_bytes()


def file_size(path):
    return Path(path).stat().st_size


def human_size(n):
    """``532 B``, ``1.4 KiB``, ``12.0 MiB`` ..."""
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024.0
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")
