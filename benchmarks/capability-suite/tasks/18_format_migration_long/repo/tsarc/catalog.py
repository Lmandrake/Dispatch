"""A catalog of the archives in a directory: what they hold and which overlap a time range."""
from dataclasses import dataclass
from pathlib import Path

from .errors import TsarcError
from .render import render_table
from .timeutil import format_ts


@dataclass
class Entry:
    path: Path
    version: object
    rows: object
    start: object
    end: object
    schema_text: str
    error: object = None

    @property
    def ok(self):
        return self.error is None

    def overlaps(self, start, end):
        """Whether the archive may hold rows with ``start <= t < end``."""
        if self.start is None:
            return False
        if start is not None and self.end < start:
            return False
        if end is not None and self.start >= end:
            return False
        return True


def scan(directory, pattern="*.tsa"):
    from .archive import ArchiveReader

    out = []
    for p in sorted(Path(directory).glob(pattern)):
        if not p.is_file():
            continue
        try:
            rd = ArchiveReader(p)
        except (TsarcError, OSError) as exc:
            out.append(Entry(p, None, None, None, None, "", exc))
            continue
        rng = rd.time_range()
        out.append(Entry(p, rd.version, rd.num_rows, rng[0] if rng else None,
                         rng[1] if rng else None, rd.schema.to_text()))
    return out


def find(entries, start=None, end=None):
    return [e for e in entries if e.ok and e.overlaps(start, end)]


def render(entries, base=None):
    rows = []
    for e in entries:
        name = str(e.path.relative_to(base)) if base else str(e.path)
        if not e.ok:
            rows.append([name, "?", "?", "-", "-", f"error: {e.error}"])
            continue
        rows.append([name, str(e.version), str(e.rows),
                     format_ts(e.start) if e.start is not None else "-",
                     format_ts(e.end) if e.end is not None else "-",
                     e.schema_text])
    return render_table(["file", "version", "rows", "first", "last", "schema"], rows,
                        align="lrrlll")
