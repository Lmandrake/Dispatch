"""Tracing: an in-memory event log built on hooks.

``Tracer(broker).install()`` subscribes to the broker's hook points and keeps
the most recent ``capacity`` events as small dicts::

    {"n": 17, "at": 1700000000.5, "point": "reserve", "job_id": "job-3", "worker": "w-1"}

``n`` counts events from 1. ``events(job_id=...)`` filters one job's history,
which is what ``taskmill trace`` and the admin API's ``/trace`` show. Tokens
are never recorded in full (only their first 6 characters), since a token
authorises acking a job.
"""

import threading
from collections import deque
from typing import Dict, List, Optional

POINTS = ("enqueue", "reserve", "heartbeat", "reap", "checkpoint", "handler.start", "handler.end")


def _short(token: Optional[str]) -> Optional[str]:
    return None if token is None else token[:6]


class Tracer:
    def __init__(self, broker, capacity: int = 10000):
        self.broker = broker
        self.capacity = capacity
        self._events = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._n = 0
        self._removers = []

    def install(self) -> "Tracer":
        if self._removers:
            return self
        for point in POINTS:
            self._removers.append(self.broker.hooks.add(point, self._make(point)))
        return self

    def uninstall(self) -> None:
        for remove in self._removers:
            remove()
        self._removers = []

    def __enter__(self):
        return self.install()

    def __exit__(self, *exc):
        self.uninstall()

    def _make(self, point: str):
        def hook(**kw):
            ev = {"point": point}
            if "job" in kw:
                job = kw["job"]
                ev.update(job_id=job.id, queue=job.queue, kind=job.kind)
            for k in ("job_id", "worker", "deadline", "last_seq", "ok"):
                if k in kw:
                    ev[k] = kw[k]
            if "token" in kw:
                ev["token"] = _short(kw["token"])
            if "expired" in kw:
                ev["expired"] = list(kw["expired"])
            self._record(ev)
        return hook

    def _record(self, ev: Dict) -> None:
        at = self.broker.clock()
        with self._lock:
            self._n += 1
            ev["n"] = self._n
            ev["at"] = at
            self._events.append(ev)

    def events(self, job_id: Optional[str] = None, point: Optional[str] = None,
               limit: Optional[int] = None) -> List[Dict]:
        with self._lock:
            evs = list(self._events)
        if job_id is not None:
            evs = [e for e in evs if e.get("job_id") == job_id or job_id in e.get("expired", ())]
        if point is not None:
            evs = [e for e in evs if e["point"] == point]
        if limit is not None:
            evs = evs[-limit:]
        return [dict(e) for e in evs]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


def format_event(ev: Dict) -> str:
    parts = [f"#{ev['n']}", f"{ev['at']:.3f}", ev["point"]]
    for k in ("job_id", "queue", "kind", "worker", "token", "deadline", "ok", "last_seq"):
        if k in ev and ev[k] is not None:
            v = ev[k]
            if k == "deadline":
                v = f"{v:.3f}"
            parts.append(f"{k}={v}")
    if ev.get("expired"):
        parts.append("expired=" + ",".join(ev["expired"]))
    return " ".join(parts)
