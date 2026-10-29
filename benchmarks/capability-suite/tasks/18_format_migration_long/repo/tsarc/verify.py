"""Integrity checking.

:func:`verify_file` fully decodes an archive and reports the outcome as a
:class:`VerifyResult`; it never raises for a damaged or unreadable file.
"""
from dataclasses import dataclass
from pathlib import Path

from .errors import TsarcError, UnsupportedVersionError


@dataclass
class VerifyResult:
    path: str
    ok: bool
    version: object = None   # int, or None when the version could not be read
    rows: object = None      # int when ok
    error: object = None     # the exception, when not ok

    def line(self):
        """The line printed by ``tsarc verify``."""
        if self.ok:
            return f"{self.path}: ok (v{self.version}, {self.rows} rows)"
        if isinstance(self.error, UnsupportedVersionError):
            return f"{self.path}: UNSUPPORTED: {self.error}"
        return f"{self.path}: CORRUPT: {self.error}"


def verify_file(path):
    from .archive import ArchiveReader

    p = str(path)
    try:
        rd = ArchiveReader(path)
    except (TsarcError, OSError) as exc:
        if isinstance(exc, OSError) and not Path(path).exists():
            return VerifyResult(p, False, error=FileNotFoundError(f"no such file: {p}"))
        return VerifyResult(p, False, error=exc)
    return VerifyResult(p, True, rd.version, rd.num_rows)


def verify_paths(paths):
    return [verify_file(p) for p in paths]
