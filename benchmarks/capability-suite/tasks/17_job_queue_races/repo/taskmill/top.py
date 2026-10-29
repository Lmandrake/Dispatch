"""A ``top``-style text dashboard for a broker.

The rendering functions are pure: they take plain data (rows built by
:func:`collect`) and return strings, so they are easy to test and to reuse in
the CLI or a web page. :class:`Dashboard` keeps the previous metrics snapshot
so each :meth:`Dashboard.render` can show rates (per second) for the counters
since the last render.

Sections: a header line, one row per queue (counts per state, oldest waiting
job age, paused flag), the active leases with the time each has left, and the
rates of the main counters.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from .errors import UnknownJob
from .job import PENDING

RATE_COUNTERS = ("jobs.enqueued", "jobs.reserved", "jobs.acked", "jobs.retried", "jobs.failed",
                 "jobs.expired", "jobs.cancelled")
STATE_COLUMNS = ("pending", "delayed", "reserved", "done", "failed", "cancelled")


@dataclass
class QueueRow:
    name: str
    counts: Dict[str, int]
    oldest_pending_age: Optional[float]
    paused: bool = False


@dataclass
class LeaseRow:
    job_id: str
    queue: str
    kind: str
    worker: Optional[str]
    remaining: float


@dataclass
class Frame:
    at: float
    queues: List[QueueRow] = field(default_factory=list)
    leases: List[LeaseRow] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    s = int(round(seconds))
    sign = "-" if s < 0 else ""
    s = abs(s)
    if s < 60:
        return f"{sign}{s}s"
    if s < 3600:
        return f"{sign}{s // 60}m{s % 60:02d}s"
    return f"{sign}{s // 3600}h{(s % 3600) // 60:02d}m"


def total_by_name(snapshot: Dict[str, float], name: str) -> float:
    """Sum of a counter across its label sets."""
    return sum(v for k, v in snapshot.items() if k == name or k.startswith(name + "{"))


def collect(broker) -> Frame:
    now = broker.clock()
    frame = Frame(at=now, metrics=broker.metrics.snapshot())
    for name in broker.queue_names():
        stats = broker.queue_stats(name)
        pending = [j for j in broker.jobs(queue=name, state=PENDING)]
        oldest = max((now - j.ready_at for j in pending), default=None)
        counts = {s: stats.get(s, 0) for s in STATE_COLUMNS}
        frame.queues.append(QueueRow(name, counts, oldest, bool(stats.get("paused"))))
    for lease in sorted(broker.leases(), key=lambda l: l["deadline"]):
        try:
            job = broker.get(lease["job_id"])
            queue, kind = job.queue, job.kind
        except UnknownJob:
            queue, kind = "?", "?"
        frame.leases.append(LeaseRow(lease["job_id"], queue, kind, lease.get("worker"),
                                     lease["deadline"] - now))
    return frame


def rates(prev: Optional[Frame], cur: Frame) -> Dict[str, float]:
    """Counter increase per second between two frames; empty without a usable interval."""
    if prev is None or cur.at <= prev.at:
        return {}
    dt = cur.at - prev.at
    return {name: (total_by_name(cur.metrics, name) - total_by_name(prev.metrics, name)) / dt
            for name in RATE_COUNTERS}


SORT_KEYS = ("name", "pending", "delayed", "reserved", "failed", "oldest")


def sort_queues(rows: List[QueueRow], key: str = "name", descending: bool = False) -> List[QueueRow]:
    if key not in SORT_KEYS:
        raise ValueError(f"sort key must be one of {', '.join(SORT_KEYS)}")
    if key == "name":
        return sorted(rows, key=lambda r: r.name, reverse=descending)
    if key == "oldest":
        return sorted(rows, key=lambda r: -1.0 if r.oldest_pending_age is None else r.oldest_pending_age,
                      reverse=not descending)
    return sorted(rows, key=lambda r: (r.counts[key], r.name), reverse=not descending)


def truncate(text: str, width: int) -> str:
    """Cut ``text`` to ``width`` characters, ending in an ellipsis when it was shortened."""
    if width < 1 or len(text) <= width:
        return text if width >= 1 else ""
    return text[:width] if width == 1 else text[: width - 1] + "\u2026"


def fit_width(text: str, width: int) -> str:
    """Truncate every line of a rendering to ``width`` characters."""
    return "\n".join(truncate(line, width) for line in text.split("\n"))


def frame_to_dict(frame: Frame, prev: Optional[Frame] = None) -> dict:
    return {"at": frame.at, "queues": [asdict(q) for q in frame.queues],
            "leases": [asdict(l) for l in frame.leases], "rates": rates(prev, frame)}


def render_json(frame: Frame, prev: Optional[Frame] = None) -> str:
    return json.dumps(frame_to_dict(frame, prev), sort_keys=True, indent=2) + "\n"


def _table(headers: Tuple[str, ...], rows: List[Tuple[str, ...]]) -> List[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]

    def line(cells):
        return "  ".join(c.ljust(widths[i]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(cells)).rstrip()

    return [line(headers)] + [line(r) for r in rows]


def render_queues(rows: List[QueueRow]) -> List[str]:
    if not rows:
        return ["(no queues)"]
    headers = ("QUEUE",) + tuple(s.upper() for s in STATE_COLUMNS) + ("OLDEST", "FLAGS")
    body = [(r.name,) + tuple(str(r.counts[s]) for s in STATE_COLUMNS)
            + (format_duration(r.oldest_pending_age), "paused" if r.paused else "") for r in rows]
    return _table(headers, body)


def render_leases(rows: List[LeaseRow]) -> List[str]:
    if not rows:
        return ["(no active leases)"]
    body = [(r.job_id, r.queue, r.kind, r.worker or "-", format_duration(r.remaining)) for r in rows]
    return _table(("JOB", "QUEUE", "KIND", "WORKER", "LEFT"), body)


def render_rates(values: Dict[str, float]) -> List[str]:
    if not values:
        return ["(rates need two snapshots)"]
    return ["  ".join(f"{name.split('.', 1)[1]} {v:.2f}/s" for name, v in values.items())]


def render(frame: Frame, prev: Optional[Frame] = None, title: str = "taskmill", sort: str = "name",
           descending: bool = False, width: Optional[int] = None) -> str:
    frame = Frame(frame.at, sort_queues(frame.queues, sort, descending), frame.leases, frame.metrics)
    totals = {s: sum(q.counts[s] for q in frame.queues) for s in STATE_COLUMNS}
    head = f"{title} - {len(frame.queues)} queue(s), " + ", ".join(f"{totals[s]} {s}" for s in STATE_COLUMNS)
    parts = [head, ""] + render_queues(frame.queues) + ["", "LEASES"] + render_leases(frame.leases)
    parts += ["", "RATES"] + render_rates(rates(prev, frame))
    text = "\n".join(parts) + "\n"
    return fit_width(text, width).rstrip("\n") + "\n" if width else text


class Dashboard:
    """Renders a broker repeatedly, remembering the previous frame for rates."""

    def __init__(self, broker, title: str = "taskmill", sort: str = "name", descending: bool = False,
                 width: Optional[int] = None, as_json: bool = False):
        self.broker = broker
        self.title = title
        self.sort = sort
        self.descending = descending
        self.width = width
        self.as_json = as_json
        self.previous: Optional[Frame] = None

    def render(self) -> str:
        frame = collect(self.broker)
        if self.as_json:
            text = render_json(frame, self.previous)
        else:
            text = render(frame, self.previous, self.title, self.sort, self.descending, self.width)
        self.previous = frame
        return text
