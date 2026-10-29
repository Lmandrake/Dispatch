"""Batched enqueues.

Producers that emit many small jobs (one per event, per row) pay a broker
call each. :class:`EnqueueBatcher` collects items and hands them to
:func:`taskmill.bulk.enqueue_many` in one go, when the batch reaches
``max_size`` or when its oldest item is ``max_age`` seconds old on the
batcher's clock. Age is only checked when the batcher is touched (``add``,
``poll``), so a ``ManualClock`` drives it deterministically; a service can
call ``poll()`` from a timer thread.

``add`` returns a :class:`Ticket`; after the flush that carried the item,
``ticket.result`` holds its :class:`~taskmill.bulk.BulkResult` (job id or the
error). The batcher is thread-safe: items are swapped out under the lock and
enqueued outside it, and concurrent flushes never send an item twice.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bulk import BulkResult, enqueue_many
from .clock import resolve


@dataclass
class Ticket:
    item: Dict[str, Any]
    result: Optional[BulkResult] = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def flushed(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: Optional[float] = None) -> Optional[BulkResult]:
        self._done.wait(timeout)
        return self.result


@dataclass
class BatchStats:
    items: int = 0
    flushes: int = 0
    by_size: int = 0
    by_age: int = 0
    manual: int = 0
    errors: int = 0
    largest: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class EnqueueBatcher:
    def __init__(self, broker, max_size: int = 100, max_age: float = 1.0, clock=None):
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        if not max_age >= 0:
            raise ValueError("max_age must be >= 0")
        self.broker = broker
        self.max_size = max_size
        self.max_age = max_age
        self.clock = resolve(clock if clock is not None else broker.clock)
        self._lock = threading.Lock()
        self._tickets: List[Ticket] = []
        self._opened_at: Optional[float] = None
        self._stats = BatchStats()
        self._closed = False

    def __len__(self) -> int:
        with self._lock:
            return len(self._tickets)

    def add(self, queue: str, kind: str, payload: Any = None, **options) -> Ticket:
        item = {"queue": queue, "kind": kind, "payload": payload, **options}
        ticket = Ticket(item)
        with self._lock:
            if self._closed:
                raise RuntimeError("batcher is closed")
            if not self._tickets:
                self._opened_at = self.clock()
            self._tickets.append(ticket)
            reason = self._due_locked()
        if reason:
            self._flush(reason)
        return ticket

    def _due_locked(self) -> Optional[str]:
        if len(self._tickets) >= self.max_size:
            return "size"
        if self._tickets and self._opened_at is not None and self.clock() - self._opened_at >= self.max_age:
            return "age"
        return None

    def poll(self) -> int:
        """Flush if the oldest item has waited long enough. Returns the number of items sent."""
        with self._lock:
            reason = self._due_locked()
        return self._flush(reason) if reason else 0

    def flush(self) -> int:
        return self._flush("manual")

    def _flush(self, reason: str) -> int:
        with self._lock:
            tickets, self._tickets = self._tickets, []
            self._opened_at = None
        if not tickets:
            return 0
        results = enqueue_many(self.broker, [t.item for t in tickets])
        errors = 0
        for ticket, result in zip(tickets, results):
            ticket.result = result
            errors += 0 if result.ok else 1
            ticket._done.set()
        with self._lock:
            s = self._stats
            s.items += len(tickets)
            s.flushes += 1
            s.errors += errors
            s.largest = max(s.largest, len(tickets))
            if reason == "size":
                s.by_size += 1
            elif reason == "age":
                s.by_age += 1
            else:
                s.manual += 1
        return len(tickets)

    def age(self) -> Optional[float]:
        """Seconds the oldest pending item has waited, or None when empty."""
        with self._lock:
            return None if self._opened_at is None else self.clock() - self._opened_at

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return self._stats.to_dict()

    def close(self) -> int:
        with self._lock:
            self._closed = True
        return self._flush("manual")

    def __enter__(self) -> "EnqueueBatcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
