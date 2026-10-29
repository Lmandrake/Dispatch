"""Waiting for results.

``Broker.wait(job_id, timeout)`` blocks until a job is finished. The broker
calls :meth:`Waiters.notify` (with its lock released) after every commit that
finishes a job; waiters re-check the job's state under the broker lock, so a
notification can never be missed between the check and the wait.

:class:`ResultView` is the read-only shape returned by ``wait`` and
``Broker.result``: the final state, the handler's result for done jobs and
the last error for failed ones.
"""

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ResultView:
    job_id: str
    state: str
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    finished_at: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.state == "done"

    def to_dict(self) -> Dict[str, Any]:
        return {"job_id": self.job_id, "state": self.state, "result": self.result, "error": self.error,
                "attempts": self.attempts, "finished_at": self.finished_at}


class Waiters:
    """A condition variable keyed by job id (one shared Condition, filtered wakeups)."""

    def __init__(self, lock):
        self._cond = threading.Condition(lock)
        self._waiting: Dict[str, int] = {}

    @property
    def cond(self) -> threading.Condition:
        return self._cond

    def wait_until(self, job_id: str, predicate, timeout: Optional[float]) -> bool:
        """Call with the broker lock HELD. Waits until ``predicate()`` is true."""
        self._waiting[job_id] = self._waiting.get(job_id, 0) + 1
        try:
            return self._cond.wait_for(predicate, timeout)
        finally:
            n = self._waiting[job_id] - 1
            if n:
                self._waiting[job_id] = n
            else:
                del self._waiting[job_id]

    def notify(self, job_ids: List[str]) -> None:
        """Call with the broker lock HELD (Condition.notify requires it)."""
        if any(j in self._waiting for j in job_ids):
            self._cond.notify_all()

    def notify_all(self) -> None:
        self._cond.notify_all()

    def waiting(self) -> int:
        return sum(self._waiting.values())


class WorkSignal:
    """Lets idle workers sleep until there may be something to reserve.

    ``pulse()`` is called after every enqueue, retry and expiry; ``wait``
    returns early when pulsed. Spurious wakeups are fine: workers just poll
    ``reserve`` again.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._generation = 0

    def pulse(self) -> None:
        with self._cond:
            self._generation += 1
            self._cond.notify_all()

    def wait(self, timeout: float, seen: int = None) -> int:
        with self._cond:
            if seen is None:
                seen = self._generation
            self._cond.wait_for(lambda: self._generation != seen, timeout)
            return self._generation

    @property
    def generation(self) -> int:
        with self._cond:
            return self._generation
