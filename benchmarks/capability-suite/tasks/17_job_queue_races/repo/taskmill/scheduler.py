"""Scheduler: enqueue jobs on cron schedules and fixed intervals.

A :class:`Schedule` names a queue, a kind and a payload, plus either a cron
expression or an ``every`` interval in seconds. ``Scheduler.tick()`` enqueues
one job for every slot that has come due since the previous tick (catching
up at most ``max_catchup`` slots per schedule; older missed slots are counted
in ``scheduler.skipped{schedule}`` and dropped).

Exactly-once per slot
---------------------
Each job is enqueued with the idempotency key ``cron/<schedule name>/<slot>``
(slot formatted ``YYYY-MM-DDTHH:MM``, or the integer slot time for interval
schedules). If two scheduler instances run against the same broker, or a
tick is retried after a crash, the duplicate enqueue returns the existing
job instead of creating a second one. This relies on distinct schedules
producing distinct keys; schedule names are case-sensitive and may contain
``a-z A-Z 0-9 _ - .``.

``tick`` records ``last_slot`` per schedule in memory only: a restarted
scheduler starts from ``now`` (no catch-up of downtime).
"""

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import check_queue_name
from .cron import CronExpr, format_slot, parse_cron
from .errors import BrokerClosed, ValidationError
from .job import validate_kind, validate_priority

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@dataclass
class Schedule:
    name: str
    queue: str
    kind: str
    payload: Any = None
    cron: Optional[str] = None
    every: Optional[float] = None
    priority: Optional[int] = None
    max_catchup: int = 1
    enabled: bool = True
    _expr: Optional[CronExpr] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not NAME_RE.match(self.name or ""):
            raise ValidationError(f"bad schedule name {self.name!r}")
        check_queue_name(self.queue)
        validate_kind(self.kind)
        if self.priority is not None:
            validate_priority(self.priority)
        if (self.cron is None) == (self.every is None):
            raise ValidationError(f"schedule {self.name}: give exactly one of cron or every")
        if self.cron is not None:
            self._expr = parse_cron(self.cron)
        elif not (self.every > 0):
            raise ValidationError(f"schedule {self.name}: every must be > 0")
        if not isinstance(self.max_catchup, int) or self.max_catchup < 1:
            raise ValidationError(f"schedule {self.name}: max_catchup must be >= 1")

    def next_slot(self, after: float) -> float:
        if self._expr is not None:
            return self._expr.next_after(after)
        n = int(after // self.every) + 1
        return n * self.every

    def slot_label(self, slot: float) -> str:
        if self._expr is not None:
            return format_slot(slot)
        return str(int(slot))

    def key(self, slot: float) -> str:
        return f"cron/{self.name}/{self.slot_label(slot)}"

    def to_dict(self) -> Dict[str, Any]:
        d = {"name": self.name, "queue": self.queue, "kind": self.kind, "payload": self.payload,
             "max_catchup": self.max_catchup, "enabled": self.enabled}
        if self.cron is not None:
            d["cron"] = self.cron
        else:
            d["every"] = self.every
        if self.priority is not None:
            d["priority"] = self.priority
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Schedule":
        allowed = {"name", "queue", "kind", "payload", "cron", "every", "priority", "max_catchup", "enabled"}
        extra = sorted(set(d) - allowed)
        if extra:
            raise ValidationError(f"schedule: unknown key(s) {', '.join(extra)}")
        return cls(**d)


@dataclass
class Fired:
    schedule: str
    slot: float
    job_id: str
    created: bool


class Scheduler:
    def __init__(self, broker, schedules: Optional[List[Schedule]] = None, start_at: Optional[float] = None):
        self.broker = broker
        self._lock = threading.Lock()
        self._schedules: Dict[str, Schedule] = {}
        self._last: Dict[str, float] = {}
        self._start_at = start_at
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        for s in schedules or []:
            self.add(s)

    def add(self, schedule: Schedule) -> None:
        with self._lock:
            if schedule.name in self._schedules:
                raise ValidationError(f"duplicate schedule {schedule.name}")
            self._schedules[schedule.name] = schedule
            start = self._start_at if self._start_at is not None else self.broker.clock()
            self._last[schedule.name] = start

    def remove(self, name: str) -> bool:
        with self._lock:
            self._last.pop(name, None)
            return self._schedules.pop(name, None) is not None

    def schedules(self) -> List[Schedule]:
        with self._lock:
            return [self._schedules[k] for k in sorted(self._schedules)]

    def due(self, now: float) -> List[tuple]:
        """``(schedule, [slots])`` that would fire at ``now``, without enqueueing."""
        out = []
        with self._lock:
            items = [(s, self._last[s.name]) for s in self._schedules.values()]
        for s, last in sorted(items, key=lambda p: p[0].name):
            if not s.enabled:
                continue
            slots = []
            t = last
            while True:
                nxt = s.next_slot(t)
                if nxt > now:
                    break
                slots.append(nxt)
                t = nxt
                if len(slots) > 10000:
                    break
            if slots:
                out.append((s, slots))
        return out

    def tick(self, now: Optional[float] = None) -> List[Fired]:
        now = self.broker.clock() if now is None else now
        fired: List[Fired] = []
        for s, slots in self.due(now):
            skipped = max(0, len(slots) - s.max_catchup)
            if skipped:
                self.broker.metrics.inc("scheduler.skipped", skipped, schedule=s.name)
            for slot in slots[skipped:]:
                res = self.broker.enqueue(s.queue, s.kind, s.payload, priority=s.priority,
                                          idempotency_key=s.key(slot))
                fired.append(Fired(s.name, slot, res.job_id, res.created))
                if res.created:
                    self.broker.metrics.inc("scheduler.fired", schedule=s.name)
            with self._lock:
                if s.name in self._last:
                    self._last[s.name] = slots[-1]
        return fired

    # ---------------------------------------------------------- background

    def start(self, interval: float = 1.0) -> "Scheduler":
        if self._thread is None:
            def loop():
                while not self._stop.wait(interval):
                    try:
                        self.tick()
                    except BrokerClosed:
                        return
            self._thread = threading.Thread(target=loop, name="taskmill-scheduler", daemon=True)
            self._thread.start()
        return self

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(wait)


def load_schedules(data) -> List[Schedule]:
    if isinstance(data, dict):
        data = data.get("schedules", [])
    if not isinstance(data, list):
        raise ValidationError("schedules must be a list")
    return [Schedule.from_dict(d) for d in data]
