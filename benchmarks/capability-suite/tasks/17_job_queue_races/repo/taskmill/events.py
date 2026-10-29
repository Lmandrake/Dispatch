"""Hooks: synchronous callbacks at named points inside taskmill.

``hooks.add(point, fn)`` registers ``fn`` and returns a function that removes
it again. ``fn`` is called in the thread doing the work, with keyword
arguments that depend on the point (see docs/HOOKS.md). Hooks are used by the
tracing integration and by tests that need to pause a thread at a known place.

A hook that raises propagates into the operation that fired it; the
operation is then abandoned as if any other error had happened at that point.

Hooks are always fired WITHOUT any broker lock held, so a hook may block or
call back into the broker.
"""

import threading
from typing import Callable, Dict, List

POINTS = (
    "enqueue",            # job=Job (after commit)
    "reserve",            # job_id, token, worker (after commit)
    "ack.before_commit",  # job_id, token (result encoded, not yet committed)
    "nack.before_commit", # job_id, token (error text prepared, not yet committed)
    "heartbeat",          # job_id, token, deadline (after renewal)
    "cancel.before_commit",  # job_id, state (a hook may raise to veto the cancel)
    "wal.append",         # record=dict (before the record is written; no lock held)
    "reap",               # expired=[job_id, ...] (after commit)
    "checkpoint.begin",   # jobs=int (state captured, snapshot not yet written)
    "checkpoint",         # last_seq=int (after the snapshot is written)
    "handler.start",      # job_id, worker
    "handler.end",        # job_id, worker, ok=bool
)


class Hooks:
    def __init__(self):
        self._lock = threading.Lock()
        self._hooks: Dict[str, List[Callable]] = {}

    def add(self, point: str, fn: Callable) -> Callable[[], None]:
        if point not in POINTS:
            raise ValueError(f"unknown hook point {point!r}")
        with self._lock:
            self._hooks.setdefault(point, []).append(fn)

        def remove() -> None:
            with self._lock:
                fns = self._hooks.get(point, [])
                if fn in fns:
                    fns.remove(fn)

        return remove

    def fire(self, point: str, **kw) -> None:
        with self._lock:
            fns = list(self._hooks.get(point, ()))
        for fn in fns:
            fn(**kw)

    def count(self, point: str = None) -> int:
        with self._lock:
            if point is None:
                return sum(len(v) for v in self._hooks.values())
            return len(self._hooks.get(point, ()))

    def clear(self) -> None:
        with self._lock:
            self._hooks.clear()
