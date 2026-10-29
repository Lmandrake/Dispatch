"""Integrity checking that reports problems instead of raising."""
from dataclasses import dataclass, field

from .errors import CorruptFileError, SenslogError
from .reader import LogReader


@dataclass
class VerifyReport:
    path: str
    ok: bool
    version: int | None = None
    record_count: int | None = None
    problems: list = field(default_factory=list)

    def describe(self):
        if self.ok:
            return f"{self.path}: OK (version {self.version}, {self.record_count} records)"
        return f"{self.path}: CORRUPT: " + "; ".join(self.problems)


def verify_file(path):
    try:
        rd = LogReader(path)
    except CorruptFileError as exc:
        return VerifyReport(str(path), False, problems=[str(exc)])
    except SenslogError as exc:
        return VerifyReport(str(path), False, problems=[str(exc)])
    except OSError as exc:
        return VerifyReport(str(path), False, problems=[f"cannot read: {exc}"])
    return VerifyReport(str(path), True, version=rd.version, record_count=len(rd))
