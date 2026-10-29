"""Import data from taskmill 1.x.

Version 1 kept every job in one ``jobs.json`` file: a JSON list of objects
with the fields ``id, queue, type, args, prio, status, tries, max_tries,
not_before, created`` and statuses ``queued, scheduled, running, ok, dead,
cancelled``.

Conversion to the 2.x model:

    queued, scheduled   pending/delayed (``not_before`` becomes ``run_at``)
    running             pending (the worker that held it is gone)
    ok                  done
    dead                failed
    cancelled           cancelled

Version 2 has no public way to insert a job that is already finished, so
finished rows are validated and reported as "skipped (finished)" instead of
imported. Waiting rows are enqueued with the priority clamped to 0-9, the
legacy id as idempotency key (re-running an import creates nothing new) and
the tag ``legacy``.

:func:`migrate` with ``dry_run=True`` validates and reports without touching
the broker. Rows that fail validation are listed in the report with every
problem found; they never abort the run.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import check_queue_name
from .errors import ConfigError, TaskmillError, ValidationError
from .job import CANCELLED, DELAYED, DONE, FAILED, PENDING, Job, validate_kind

LEGACY_FIELDS = ("id", "queue", "type", "args", "prio", "status", "tries", "max_tries", "not_before", "created")
STATUS_MAP = {"queued": PENDING, "scheduled": PENDING, "running": PENDING,
              "ok": DONE, "dead": FAILED, "cancelled": CANCELLED}
FINISHED_STATUSES = frozenset({"ok", "dead", "cancelled"})
LEGACY_TAG = "legacy"


@dataclass
class RowProblem:
    index: int
    legacy_id: Any
    problems: List[str]

    def __str__(self) -> str:
        return f"row {self.index} ({self.legacy_id!r}): " + "; ".join(self.problems)


@dataclass
class MigrationReport:
    dry_run: bool
    total: int = 0
    imported: List[str] = field(default_factory=list)
    skipped_finished: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    errors: List[RowProblem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"dry_run": self.dry_run, "total": self.total, "imported": list(self.imported),
                "skipped_finished": list(self.skipped_finished), "duplicates": list(self.duplicates),
                "errors": [{"index": e.index, "id": e.legacy_id, "problems": e.problems} for e in self.errors]}

    def render(self) -> str:
        head = "dry run: " if self.dry_run else ""
        lines = [f"{head}{self.total} row(s): {len(self.imported)} imported, "
                 f"{len(self.skipped_finished)} skipped (finished), {len(self.duplicates)} already present, "
                 f"{len(self.errors)} invalid"]
        lines += [f"  {e}" for e in self.errors]
        return "\n".join(lines)


def load_legacy(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValidationError(f"{path}: expected a JSON list of jobs")
    return data


def _number(row: dict, name: str, problems: List[str], minimum: float = 0, integer: bool = False):
    v = row.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (integer and not isinstance(v, int)):
        problems.append(f"{name} must be {'an integer' if integer else 'a number'}")
        return None
    if v < minimum:
        problems.append(f"{name} must be >= {minimum}")
        return None
    return v


def check_row(row: Any) -> List[str]:
    """Every problem with one legacy row (empty when it is valid)."""
    if not isinstance(row, dict):
        return ["row is not an object"]
    problems = [f"missing field {f}" for f in LEGACY_FIELDS if f not in row]
    if problems:
        return problems
    unknown = sorted(set(row) - set(LEGACY_FIELDS))
    problems += [f"unknown field {f}" for f in unknown]
    if not isinstance(row["id"], (str, int)) or isinstance(row["id"], bool) or row["id"] == "":
        problems.append("id must be a non-empty string or integer")
    try:
        check_queue_name(row["queue"])
    except ConfigError as exc:
        problems.append(str(exc))
    try:
        validate_kind(row["type"])
    except ValidationError as exc:
        problems.append(str(exc))
    if row["status"] not in STATUS_MAP:
        problems.append(f"unknown status {row['status']!r}")
    _number(row, "prio", problems, minimum=-(10 ** 9), integer=True)
    _number(row, "tries", problems, integer=True)
    _number(row, "max_tries", problems, minimum=1, integer=True)
    _number(row, "not_before", problems)
    _number(row, "created", problems)
    return problems


def clamp_priority(prio: int) -> int:
    return max(0, min(9, prio))


def to_job_dict(row: dict, now: float) -> Dict[str, Any]:
    """The 2.x Job dict a valid legacy row maps to (state per the table above)."""
    state = STATUS_MAP[row["status"]]
    run_at = max(float(row["not_before"]), float(row["created"]))
    if state == PENDING and run_at > now:
        state = DELAYED
    finished = state in (DONE, FAILED, CANCELLED)
    legacy_id = str(row["id"])
    return Job(
        id=f"legacy-{legacy_id}", queue=row["queue"], kind=row["type"], payload=row["args"],
        priority=clamp_priority(row["prio"]), state=state, enqueued_at=float(row["created"]),
        run_at=run_at, ready_at=run_at, attempts=int(row["tries"]), max_attempts=int(row["max_tries"]),
        idempotency_key=legacy_id, tags=[LEGACY_TAG], finished_at=now if finished else None,
        result=None,
    ).to_dict()


def migrate(rows: List[Any], broker, dry_run: bool = False) -> MigrationReport:
    report = MigrationReport(dry_run=dry_run, total=len(rows))
    now = broker.clock()
    for index, row in enumerate(rows):
        problems = check_row(row)
        legacy_id = row.get("id") if isinstance(row, dict) else None
        if problems:
            report.errors.append(RowProblem(index, legacy_id, problems))
            continue
        if row["status"] in FINISHED_STATUSES:
            report.skipped_finished.append(str(legacy_id))
            continue
        _import_row(broker, row, index, now, dry_run, report)
    return report


def _import_row(broker, row: dict, index: int, now: float, dry_run: bool, report: MigrationReport) -> None:
    legacy_id = str(row["id"])
    if dry_run:
        report.imported.append(legacy_id)
        return
    run_at = max(float(row["not_before"]), 0.0)
    try:
        result = broker.enqueue(
            row["queue"], row["type"], row["args"], priority=clamp_priority(row["prio"]),
            run_at=run_at if run_at > now else None, idempotency_key=f"legacy-{legacy_id}",
            max_attempts=int(row["max_tries"]), tags=[LEGACY_TAG])
    except TaskmillError as exc:
        report.errors.append(RowProblem(index, legacy_id, [str(exc)]))
        return
    (report.imported if result.created else report.duplicates).append(legacy_id)


def migrate_file(path: str, broker, dry_run: bool = False) -> MigrationReport:
    return migrate(load_legacy(path), broker, dry_run=dry_run)
