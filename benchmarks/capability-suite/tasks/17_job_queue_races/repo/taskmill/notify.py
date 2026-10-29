"""Completion notifications: an outbox of "job finished" events.

Some clients cannot block in ``Broker.wait``; they register a subscriber
instead. :class:`Outbox` watches the broker (through ``handler.end`` and an
explicit :meth:`Outbox.poll`) and delivers one :class:`Notification` per
finished job to every subscriber whose filter matches, in job-finish order.

Delivery is at-least-once per subscriber: a subscriber that raises is
retried on the next ``flush`` (up to ``max_tries`` times, then the
notification is dropped and counted in ``dropped``). Subscribers are called
outside every lock, in the thread that calls ``flush``.

The outbox is in-memory only. It is meant for in-process integrations (a
webhook sender, a cache invalidator); durable consumers should poll
``Broker.jobs(state="done")`` instead.
"""

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Set

from .job import FINISHED


@dataclass(frozen=True)
class Notification:
    job_id: str
    queue: str
    kind: str
    state: str
    finished_at: Optional[float]


@dataclass
class _Sub:
    name: str
    fn: Callable[[Notification], None]
    queues: Optional[Set[str]] = None
    states: Optional[Set[str]] = None
    pending: Deque = field(default_factory=deque)
    tries: Dict[str, int] = field(default_factory=dict)
    delivered: int = 0
    dropped: int = 0

    def wants(self, n: Notification) -> bool:
        return (self.queues is None or n.queue in self.queues) and (self.states is None or n.state in self.states)


class Outbox:
    def __init__(self, broker, max_tries: int = 5):
        self.broker = broker
        self.max_tries = max_tries
        self._lock = threading.Lock()
        self._subs: Dict[str, _Sub] = {}
        self._seen: Set[str] = set()
        self._remove = None

    def subscribe(self, name: str, fn: Callable[[Notification], None], queues=None, states=None) -> None:
        with self._lock:
            if name in self._subs:
                raise ValueError(f"duplicate subscriber {name}")
            self._subs[name] = _Sub(name, fn, None if queues is None else set(queues),
                                    None if states is None else set(states))

    def unsubscribe(self, name: str) -> bool:
        with self._lock:
            return self._subs.pop(name, None) is not None

    def install(self) -> "Outbox":
        if self._remove is None:
            self._remove = self.broker.hooks.add("handler.end", lambda **kw: self.poll())
        return self

    def uninstall(self) -> None:
        if self._remove is not None:
            self._remove()
            self._remove = None

    def poll(self) -> int:
        """Queue notifications for jobs that finished since the last poll."""
        finished = [j for j in self.broker.jobs() if j.state in FINISHED]
        finished.sort(key=lambda j: (j.finished_at or 0.0, j.seq))
        n = 0
        with self._lock:
            for j in finished:
                if j.id in self._seen:
                    continue
                self._seen.add(j.id)
                note = Notification(j.id, j.queue, j.kind, j.state, j.finished_at)
                for sub in self._subs.values():
                    if sub.wants(note):
                        sub.pending.append(note)
                n += 1
        return n

    def flush(self) -> Dict[str, int]:
        """Deliver pending notifications. Returns deliveries per subscriber."""
        with self._lock:
            subs = list(self._subs.values())
        out = {}
        for sub in subs:
            delivered = 0
            while True:
                with self._lock:
                    if not sub.pending:
                        break
                    note = sub.pending[0]
                try:
                    sub.fn(note)
                except Exception:  # noqa: BLE001 - subscriber failures are retried
                    with self._lock:
                        sub.tries[note.job_id] = sub.tries.get(note.job_id, 0) + 1
                        if sub.tries[note.job_id] >= self.max_tries:
                            sub.pending.popleft()
                            sub.tries.pop(note.job_id, None)
                            sub.dropped += 1
                            continue
                    break
                with self._lock:
                    sub.pending.popleft()
                    sub.tries.pop(note.job_id, None)
                    sub.delivered += 1
                delivered += 1
            out[sub.name] = delivered
        return out

    def backlog(self) -> Dict[str, int]:
        with self._lock:
            return {name: len(s.pending) for name, s in sorted(self._subs.items())}

    def counts(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return {name: {"delivered": s.delivered, "dropped": s.dropped, "pending": len(s.pending)}
                    for name, s in sorted(self._subs.items())}

    def forget(self, job_ids: List[str]) -> None:
        """Allow notifications for these ids again (after an operator retry)."""
        with self._lock:
            for j in job_ids:
                self._seen.discard(j)
