"""Liveness and readiness checks for a broker or a runtime.

:func:`check` accepts a :class:`~taskmill.broker.Broker` or anything with a
``broker`` attribute (a :class:`~taskmill.runtime.Runtime`) and returns a
:class:`HealthReport` of individual :class:`CheckResult` entries, each ``ok``,
``warn`` or ``fail``:

``broker``       the broker is open (liveness)
``backlog``      jobs waiting per queue against ``Thresholds.max_backlog``
``oldest``       age of the oldest pending job against ``max_oldest_pending``
``leases``       active leases against ``max_leases``
``wal``          the WAL directory exists and a file can be created in it
``checkpoint``   age of the newest snapshot against ``max_checkpoint_age``

Thresholds are ``(warn, fail)`` pairs; ``None`` disables a check. Paused
queues are excluded from backlog and oldest-pending, since a paused queue is
expected to accumulate. :attr:`HealthReport.live` is true when the broker is
open; :attr:`HealthReport.ready` when nothing failed. Disk checks are skipped
(reported ``ok`` with detail "in-memory") for a broker without a data dir.
"""

import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import recovery
from . import snapshot as snapmod
from .errors import SnapshotError
from .job import PENDING

OK, WARN, FAIL = "ok", "warn", "fail"
RANK = {OK: 0, WARN: 1, FAIL: 2}
Pair = Optional[Tuple[float, float]]


@dataclass
class Thresholds:
    max_backlog: Pair = (1000, 5000)
    max_oldest_pending: Pair = (60.0, 300.0)
    max_leases: Pair = None
    max_checkpoint_age: Pair = (3600.0, 86400.0)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    value: Optional[float] = None

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail, "value": self.value}


@dataclass
class HealthReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        return max((r.status for r in self.results), key=RANK.get, default=OK)

    @property
    def live(self) -> bool:
        return all(r.status != FAIL for r in self.results if r.name == "broker")

    @property
    def ready(self) -> bool:
        return self.status != FAIL

    def get(self, name: str) -> Optional[CheckResult]:
        return next((r for r in self.results if r.name == name), None)

    def to_dict(self) -> dict:
        return {"status": self.status, "live": self.live, "ready": self.ready,
                "checks": [r.to_dict() for r in self.results]}

    def render(self) -> str:
        lines = [f"health: {self.status.upper()} (live={self.live}, ready={self.ready})"]
        lines += [f"  [{r.status:<4}] {r.name:<10} {r.detail}" for r in self.results]
        return "\n".join(lines) + "\n"


def grade(value: float, pair: Pair) -> str:
    if pair is None:
        return OK
    warn, fail = pair
    return FAIL if value >= fail else WARN if value >= warn else OK


def _broker_of(target):
    return getattr(target, "broker", target)


def check_broker(broker) -> CheckResult:
    if broker.closed:
        return CheckResult("broker", FAIL, "broker is closed")
    return CheckResult("broker", OK, "open")


def check_queues(broker, t: Thresholds) -> List[CheckResult]:
    now = broker.clock()
    paused = set(broker.stats()["paused"])
    backlog: Dict[str, int] = {}
    oldest = 0.0
    for name in broker.queue_names():
        if name in paused:
            continue
        counts = broker.queue_stats(name)
        backlog[name] = counts["pending"] + counts["delayed"]
        ages = [now - j.ready_at for j in broker.jobs(queue=name, state=PENDING)]
        oldest = max([oldest] + ages)
    worst = max(backlog.values(), default=0)
    where = max(backlog, key=backlog.get) if backlog else "-"
    return [
        CheckResult("backlog", grade(worst, t.max_backlog), f"largest backlog {worst} on {where}", worst),
        CheckResult("oldest", grade(oldest, t.max_oldest_pending), f"oldest pending {oldest:.0f}s", oldest),
    ]


def check_leases(broker, t: Thresholds) -> CheckResult:
    n = len(broker.leases())
    return CheckResult("leases", grade(n, t.max_leases), f"{n} active lease(s)", n)


def check_wal(broker) -> CheckResult:
    if broker.data_dir is None:
        return CheckResult("wal", OK, "in-memory")
    path = recovery.wal_dir(broker.data_dir)
    if not os.path.isdir(path):
        return CheckResult("wal", FAIL, f"{path} is missing")
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".health-"):
            pass
    except OSError as exc:
        return CheckResult("wal", FAIL, f"{path} is not writable: {exc.strerror or exc}")
    return CheckResult("wal", OK, f"{path} writable")


def check_checkpoint(broker, t: Thresholds) -> CheckResult:
    if broker.data_dir is None:
        return CheckResult("checkpoint", OK, "in-memory")
    paths = snapmod.list_snapshots(recovery.snapshot_dir(broker.data_dir))
    if not paths:
        return CheckResult("checkpoint", WARN, "no snapshot yet")
    try:
        age = broker.clock() - snapmod.read_snapshot(paths[0]).created_at
    except SnapshotError as exc:
        return CheckResult("checkpoint", FAIL, f"newest snapshot unreadable: {exc}")
    return CheckResult("checkpoint", grade(age, t.max_checkpoint_age), f"last checkpoint {age:.0f}s ago", age)


def check(target, thresholds: Optional[Thresholds] = None) -> HealthReport:
    t = thresholds or Thresholds()
    broker = _broker_of(target)
    report = HealthReport([check_broker(broker)])
    if broker.closed:
        return report
    report.results += check_queues(broker, t)
    report.results.append(check_leases(broker, t))
    report.results.append(check_wal(broker))
    report.results.append(check_checkpoint(broker, t))
    return report


def liveness(target) -> bool:
    return check_broker(_broker_of(target)).status == OK


def readiness(target, thresholds: Optional[Thresholds] = None) -> bool:
    return check(target, thresholds).ready
