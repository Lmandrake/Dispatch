"""Metrics: counters, gauges and histograms with optional labels.

Metric names and the snapshot format are listed in docs/METRICS.md.
"""

import math
import threading
from typing import Dict, Iterable, Optional, Tuple

from .clock import resolve

DEFAULT_BUCKETS = (0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 60.0)


def series_name(name: str, labels: Dict[str, str]) -> str:
    if not labels:
        return name
    inner = ",".join(f"{k}={labels[k]}" for k in sorted(labels))
    return f"{name}{{{inner}}}"


def _label_key(labels: Dict[str, object]) -> Tuple:
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


class Counter:
    def __init__(self, name: str, clock, lock):
        self.name = name
        self._clock = clock
        self._lock = lock
        self._values: Dict[Tuple, float] = {}
        self._updated: Dict[Tuple, float] = {}

    def inc(self, n: float = 1, **labels) -> None:
        if n < 0:
            raise ValueError("counters only go up")
        key = _label_key(labels)
        value = self._values.get(key, 0) + n
        self._updated[key] = self._clock()
        self._values[key] = value

    def get(self, **labels) -> float:
        return self._values.get(_label_key(labels), 0)

    def total(self) -> float:
        with self._lock:
            return sum(self._values.values())

    def last_updated(self, **labels) -> Optional[float]:
        return self._updated.get(_label_key(labels))

    def series(self) -> Dict[str, float]:
        with self._lock:
            items = list(self._values.items())
        return {series_name(self.name, dict(k)): v for k, v in items}

    def reset(self) -> None:
        with self._lock:
            self._values.clear()
            self._updated.clear()


class Gauge:
    def __init__(self, name: str, lock):
        self.name = name
        self._lock = lock
        self._values: Dict[Tuple, float] = {}

    def set(self, value: float, **labels) -> None:
        with self._lock:
            self._values[_label_key(labels)] = value

    def get(self, **labels) -> Optional[float]:
        with self._lock:
            return self._values.get(_label_key(labels))

    def series(self) -> Dict[str, float]:
        with self._lock:
            items = list(self._values.items())
        return {series_name(self.name, dict(k)): v for k, v in items}

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


class Histogram:
    def __init__(self, name: str, clock, lock, buckets: Iterable[float] = DEFAULT_BUCKETS):
        self.name = name
        self._clock = clock
        self._lock = lock
        self.buckets = tuple(sorted(buckets))
        self._count = 0
        self._sum = 0.0
        self._max = -math.inf
        self._bucket_counts = [0] * len(self.buckets)
        self._updated: Optional[float] = None

    def observe(self, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("observations must be finite")
        count = self._count + 1
        total = self._sum + value
        self._updated = self._clock()
        self._count = count
        self._sum = total
        if value > self._max:
            self._max = value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self._bucket_counts[i] += 1

    @property
    def count(self) -> int:
        return self._count

    @property
    def sum(self) -> float:
        return self._sum

    @property
    def max(self) -> Optional[float]:
        return None if self._count == 0 else self._max

    def bucket_counts(self) -> Dict[float, int]:
        with self._lock:
            return dict(zip(self.buckets, self._bucket_counts))

    def series(self) -> Dict[str, float]:
        with self._lock:
            out = {f"{self.name}.count": self._count, f"{self.name}.sum": self._sum}
            if self._count:
                out[f"{self.name}.max"] = self._max
            for bound, n in zip(self.buckets, self._bucket_counts):
                out[f"{self.name}.le_{bound:g}"] = n
        return out

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._sum = 0.0
            self._max = -math.inf
            self._bucket_counts = [0] * len(self.buckets)
            self._updated = None


class Metrics:
    def __init__(self, clock=None):
        self._clock = resolve(clock)
        self._lock = threading.Lock()
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}

    def _check_free(self, name: str, kind: dict) -> None:
        for other in (self._counters, self._gauges, self._histograms):
            if other is not kind and name in other:
                raise ValueError(f"metric {name!r} already registered with another type")

    def counter(self, name: str) -> Counter:
        with self._lock:
            c = self._counters.get(name)
            if c is None:
                self._check_free(name, self._counters)
                c = self._counters[name] = Counter(name, self._clock, self._lock)
            return c

    def gauge(self, name: str) -> Gauge:
        with self._lock:
            g = self._gauges.get(name)
            if g is None:
                self._check_free(name, self._gauges)
                g = self._gauges[name] = Gauge(name, self._lock)
            return g

    def histogram(self, name: str, buckets: Iterable[float] = DEFAULT_BUCKETS) -> Histogram:
        with self._lock:
            h = self._histograms.get(name)
            if h is None:
                self._check_free(name, self._histograms)
                h = self._histograms[name] = Histogram(name, self._clock, self._lock, buckets)
            return h

    # convenience
    def inc(self, name: str, n: float = 1, **labels) -> None:
        self.counter(name).inc(n, **labels)

    def observe(self, name: str, value: float) -> None:
        self.histogram(name).observe(value)

    def value(self, name: str, **labels) -> float:
        """A counter's (or gauge's) value; 0 for a counter nobody has touched."""
        with self._lock:
            c = self._counters.get(name)
            g = self._gauges.get(name)
        if c is not None:
            return c.get(**labels)
        if g is not None:
            v = g.get(**labels)
            return 0 if v is None else v
        return 0

    def snapshot(self, prefix: Optional[str] = None) -> Dict[str, float]:
        with self._lock:
            metrics = list(self._counters.values()) + list(self._gauges.values()) + list(self._histograms.values())
        out: Dict[str, float] = {}
        for m in metrics:
            out.update(m.series())
        if prefix is not None:
            p = prefix + "."
            out = {k: v for k, v in out.items() if k.startswith(p)}
        return dict(sorted(out.items()))

    def render_text(self) -> str:
        lines = []
        for k, v in self.snapshot().items():
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            lines.append(f"{k} {v}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            metrics = list(self._counters.values()) + list(self._gauges.values()) + list(self._histograms.values())
        for m in metrics:
            m.reset()
