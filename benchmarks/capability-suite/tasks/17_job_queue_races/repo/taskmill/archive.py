"""Long-term archive of finished jobs.

Finished jobs are written to gzip-compressed JSON-lines files, one per UTC
day of ``finished_at``, named ``archive-YYYY-MM-DD.jsonl.gz``, under one
directory. Each line is the canonical JSON form of ``Job.to_dict()``.

Archiving is idempotent: a job whose id is already in its day file is skipped,
so :func:`archive_then_purge` can be re-run after a crash between the two
steps without duplicating records. Day files are rewritten through a
temporary file and an atomic rename.

:func:`archive_then_purge` archives exactly the jobs ``Broker.purge`` is about
to remove (finished at or before ``now - retention``) and then purges.
"""

import gzip
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Iterator, List, Optional

from . import codec
from .job import FINISHED, Job

NAME_RE = re.compile(r"^archive-(\d{4}-\d{2}-\d{2})\.jsonl\.gz$")


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def archive_name(day: str) -> str:
    return f"archive-{day}.jsonl.gz"


@dataclass(frozen=True)
class ArchiveFile:
    day: str
    path: str
    bytes: int
    jobs: int


@dataclass
class ArchiveReport:
    written: int = 0
    skipped: int = 0
    days: List[str] = field(default_factory=list)
    purged: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"written": self.written, "skipped": self.skipped, "days": list(self.days),
                "purged": list(self.purged)}


class Archive:
    def __init__(self, directory: str):
        self.directory = directory

    def path_for(self, day: str) -> str:
        return os.path.join(self.directory, archive_name(day))

    def days(self) -> List[str]:
        if not os.path.isdir(self.directory):
            return []
        found = (NAME_RE.match(n) for n in os.listdir(self.directory))
        return sorted(m.group(1) for m in found if m)

    def _read_day(self, day: str) -> List[dict]:
        path = self.path_for(day)
        if not os.path.exists(path):
            return []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return [codec.loads(line) for line in fh if line.strip()]

    def _write_day(self, day: str, records: List[dict]) -> None:
        os.makedirs(self.directory, exist_ok=True)
        path = self.path_for(day)
        tmp = path + ".tmp"
        with gzip.GzipFile(tmp, "wb", mtime=0) as fh:
            for rec in records:
                fh.write(codec.encode(rec) + b"\n")
        os.replace(tmp, path)

    def add(self, jobs: Iterable[Job]) -> ArchiveReport:
        """Append finished jobs to their day files, skipping ids already archived."""
        by_day: Dict[str, List[Job]] = {}
        for job in jobs:
            if job.state not in FINISHED or job.finished_at is None:
                raise ValueError(f"{job.id} is not finished and cannot be archived")
            by_day.setdefault(day_of(job.finished_at), []).append(job)
        report = ArchiveReport()
        for day in sorted(by_day):
            existing = self._read_day(day)
            known = {r["id"] for r in existing}
            fresh = []
            for job in by_day[day]:
                if job.id in known:
                    report.skipped += 1
                else:
                    known.add(job.id)
                    fresh.append(job.to_dict())
            if fresh:
                self._write_day(day, existing + fresh)
                report.written += len(fresh)
                report.days.append(day)
        return report

    def iter_records(self, since: Optional[str] = None, until: Optional[str] = None) -> Iterator[dict]:
        """Archived job dicts in day order, then file order; ``since``/``until`` are inclusive days."""
        for day in self.days():
            if (since is not None and day < since) or (until is not None and day > until):
                continue
            yield from self._read_day(day)

    def get(self, job_id: str) -> Optional[dict]:
        for rec in self.iter_records():
            if rec["id"] == job_id:
                return rec
        return None

    def search(self, kind: Optional[str] = None, queue: Optional[str] = None, state: Optional[str] = None,
               since: Optional[str] = None, until: Optional[str] = None) -> List[dict]:
        return [r for r in self.iter_records(since, until)
                if (kind is None or r["kind"] == kind)
                and (queue is None or r["queue"] == queue)
                and (state is None or r["state"] == state)]

    def count(self) -> int:
        return sum(len(self._read_day(d)) for d in self.days())

    def restore(self, job_id: str) -> Optional[Job]:
        rec = self.get(job_id)
        return None if rec is None else Job.from_dict(rec)

    def files(self) -> List[ArchiveFile]:
        """One entry per day file: size on disk and number of archived jobs."""
        out = []
        for day in self.days():
            path = self.path_for(day)
            out.append(ArchiveFile(day, path, os.path.getsize(path), len(self._read_day(day))))
        return out

    def stats(self) -> Dict[str, object]:
        files = self.files()
        by_state: Dict[str, int] = {}
        by_kind: Dict[str, int] = {}
        for rec in self.iter_records():
            by_state[rec["state"]] = by_state.get(rec["state"], 0) + 1
            by_kind[rec["kind"]] = by_kind.get(rec["kind"], 0) + 1
        return {"files": len(files), "jobs": sum(f.jobs for f in files),
                "bytes": sum(f.bytes for f in files),
                "first_day": files[0].day if files else None, "last_day": files[-1].day if files else None,
                "by_state": dict(sorted(by_state.items())), "by_kind": dict(sorted(by_kind.items()))}

    def prune_older_than(self, day: str) -> List[str]:
        """Delete day files strictly before ``day`` (YYYY-MM-DD). Returns the days removed."""
        removed = []
        for d in self.days():
            if d < day:
                os.remove(self.path_for(d))
                removed.append(d)
        return removed

    def prune_keep_days(self, keep: int, today: Optional[str] = None) -> List[str]:
        """Keep the newest ``keep`` days counting back from ``today`` (default: the newest file)."""
        if keep < 1:
            raise ValueError("keep must be at least 1")
        days = self.days()
        if not days:
            return []
        last = datetime.strptime(today or days[-1], "%Y-%m-%d")
        cutoff = (last - timedelta(days=keep - 1)).strftime("%Y-%m-%d")
        return self.prune_older_than(cutoff)

    def export_jsonl(self, path: str, since: Optional[str] = None, until: Optional[str] = None,
                     kind: Optional[str] = None) -> int:
        """Write matching archived jobs to a plain (uncompressed) JSONL file. Returns the count."""
        n = 0
        with open(path, "wb") as fh:
            for rec in self.iter_records(since, until):
                if kind is None or rec["kind"] == kind:
                    fh.write(codec.encode(rec) + b"\n")
                    n += 1
        return n


def purgeable(broker) -> List[Job]:
    """The finished jobs ``broker.purge()`` would remove right now."""
    cutoff = broker.clock() - broker.config.retention
    return [j for j in broker.jobs()
            if j.state in FINISHED and j.finished_at is not None and j.finished_at <= cutoff]


def archive_then_purge(broker, directory: str) -> ArchiveReport:
    report = Archive(directory).add(purgeable(broker))
    report.purged = broker.purge()
    return report
