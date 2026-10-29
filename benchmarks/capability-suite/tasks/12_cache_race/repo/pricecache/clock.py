"""Time sources.

Everything that needs the time takes a ``clock`` callable returning seconds as
a float, so tests can drive expiry without sleeping.
"""

import threading
import time


class SystemClock:
    """Monotonic wall clock. The default everywhere."""

    def __call__(self) -> float:
        return time.monotonic()

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
