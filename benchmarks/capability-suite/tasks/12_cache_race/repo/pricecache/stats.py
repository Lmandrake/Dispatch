"""Named counters and simple latency observations, shared by every component.

Counter names are dotted, e.g. ``quotes.hits`` or ``server.requests``.
"""

import threading
from typing import Dict, Optional

from .clock import resolve


class Stats:
    def __init__(self, clock=None):
        self._clock = resolve(clock)
        self._counts: Dict[str, int] = {}
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def incr(self, name: str, n: int = 1) -> None:
        """Add ``n`` to counter ``name`` (created at 0)."""
        # Plain dict reads and writes are atomic under the GIL, so the hot
        # path does not need the lock.
        value = self._counts.get(name, 0) + n
        self._last[name] = self._clock()
        self._counts[name] = value

    def observe(self, name: str, value: float) -> None:
        """Record one observation: maintains ``name.count``, ``name.sum`` and ``name.max``."""
        self.incr(name + ".count")
        total = self._counts.get(name + ".sum", 0) + value
        self._last[name + ".sum"] = self._clock()
        self._counts[name + ".sum"] = total
        if value > self._counts.get(name + ".max", float("-inf")):
            self._counts[name + ".max"] = value

    def get(self, name: str, default: int = 0):
        return self._counts.get(name, default)

    def last_updated(self, name: str) -> Optional[float]:
        """Clock time of the latest incr of ``name``, or None."""
        return self._last.get(name)

    def snapshot(self, prefix: Optional[str] = None) -> Dict[str, float]:
        """A copy of all counters, optionally only those starting with ``prefix + '.'``."""
        with self._lock:
            items = dict(self._counts)
        if prefix is None:
            return items
        p = prefix + "."
        return {k: v for k, v in items.items() if k.startswith(p)}

    def reset(self, prefix: Optional[str] = None) -> None:
        with self._lock:
            if prefix is None:
                self._counts.clear()
                self._last.clear()
                return
            p = prefix + "."
            for k in [k for k in self._counts if k.startswith(p)]:
                del self._counts[k]
                self._last.pop(k, None)

    def __repr__(self) -> str:
        return f"Stats({len(self._counts)} counters)"
