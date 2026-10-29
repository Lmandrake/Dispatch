"""Time sources.

Everything in taskmill that needs the time takes a ``clock`` callable that
returns seconds as a float. Production uses :class:`SystemClock` (wall-clock
seconds since the epoch, so that timestamps in the WAL and in snapshots mean
something to an operator); tests use :class:`ManualClock` so that leases,
delays and backoff can be driven without sleeping.

Waiting is separate from telling the time: components that block (the reaper,
the heartbeater, worker polling) wait on ``threading.Event`` objects with real
timeouts, so they can always be stopped promptly whatever the clock says.
"""

import threading
import time


class SystemClock:
    """Wall clock (``time.time``). The default everywhere."""

    def __call__(self) -> float:
        return time.time()

    def __repr__(self) -> str:
        return "SystemClock()"


class ManualClock:
    """A clock that only moves when told to. Safe to share between threads."""

    def __init__(self, start: float = 0.0):
        self._now = float(start)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> float:
        if seconds < 0:
            raise ValueError("a clock cannot go backwards")
        with self._lock:
            self._now += seconds
            return self._now

    def set(self, now: float) -> None:
        with self._lock:
            if now < self._now:
                raise ValueError("a clock cannot go backwards")
            self._now = float(now)

    def __repr__(self) -> str:
        return f"ManualClock({self._now!r})"


def resolve(clock):
    """Return ``clock`` or a SystemClock when it is None."""
    return SystemClock() if clock is None else clock
