"""Retry backoff policies (rules: docs/RETRIES.md).

Policies are small JSON objects so they can live in configuration and in the
WAL: ``fixed`` (delay), ``linear`` (base, step), ``exponential`` (base,
factor), each with optional ``max`` and ``jitter`` (none, full, equal).
"""

import hashlib
import random
from dataclasses import dataclass
from typing import List, Optional

from .errors import ConfigError

JITTERS = ("none", "full", "equal", "decorrelated")
KINDS = ("fixed", "linear", "exponential")


def _num(spec: dict, name: str, default=None, minimum: float = 0.0) -> float:
    if name not in spec:
        if default is None:
            raise ConfigError(f"backoff: missing {name!r}")
        return float(default)
    v = spec[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"backoff: {name} must be a number")
    if v < minimum:
        raise ConfigError(f"backoff: {name} must be >= {minimum}")
    return float(v)


@dataclass(frozen=True)
class Backoff:
    kind: str
    base: float = 0.0
    step: float = 0.0
    factor: float = 1.0
    max: Optional[float] = None
    jitter: str = "none"

    def raw_delay(self, attempt: int) -> float:
        """The delay before jitter for the retry after ``attempt`` failures."""
        if attempt < 1:
            raise ValueError("attempt counts from 1")
        if self.kind == "fixed":
            d = self.base
        elif self.kind == "linear":
            d = self.base + self.step * (attempt - 1)
        else:
            # Avoid overflow for huge attempt numbers: once we pass max, stop multiplying.
            d = self.base
            for _ in range(attempt - 1):
                d *= self.factor
                if self.max is not None and d >= self.max:
                    break
        if self.max is not None:
            d = min(d, self.max)
        return d

    def delay(self, attempt: int, job_id: str = "") -> float:
        if self.jitter == "decorrelated":
            return self._decorrelated(attempt, job_id)
        d = self.raw_delay(attempt)
        if self.jitter == "none" or d == 0:
            return d
        rng = random.Random(_seed(job_id, attempt))
        if self.jitter == "full":
            return rng.uniform(0.0, d)
        return d / 2 + rng.uniform(0.0, d / 2)

    def _decorrelated(self, attempt: int, job_id: str) -> float:
        if attempt < 1:
            raise ValueError("attempt counts from 1")
        prev = self.base
        for a in range(1, attempt + 1):
            rng = random.Random(_seed(job_id, a))
            prev = rng.uniform(self.base, max(self.base, prev * 3))
        return prev

    def schedule(self, attempts: int, job_id: str = "") -> List[float]:
        """Delays for attempts 1..attempts (handy for ``taskmill backoff`` and the docs)."""
        return [self.delay(a, job_id) for a in range(1, attempts + 1)]

    def to_dict(self) -> dict:
        if self.kind == "fixed":
            d = {"kind": "fixed", "delay": self.base}
        elif self.kind == "linear":
            d = {"kind": "linear", "base": self.base, "step": self.step}
        else:
            d = {"kind": "exponential", "base": self.base, "factor": self.factor}
        if self.max is not None:
            d["max"] = self.max
        d["jitter"] = self.jitter
        return d

    def describe(self) -> str:
        if self.kind == "fixed":
            core = f"fixed {self.base:g}s"
        elif self.kind == "linear":
            core = f"linear {self.base:g}s + {self.step:g}s/attempt"
        else:
            core = f"exponential {self.base:g}s x{self.factor:g}"
        if self.max is not None:
            core += f", max {self.max:g}s"
        if self.jitter != "none":
            core += f", {self.jitter} jitter"
        return core


def _seed(job_id: str, attempt: int) -> int:
    h = hashlib.sha256(f"{job_id}\x00{attempt}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def parse_backoff(spec) -> Backoff:
    """Validate a backoff description and return a :class:`Backoff`."""
    if isinstance(spec, Backoff):
        return spec
    if not isinstance(spec, dict):
        raise ConfigError("backoff must be an object")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ConfigError(f"backoff: kind must be one of {', '.join(KINDS)}")
    allowed = {"kind", "jitter", "max"} | {
        "fixed": {"delay"}, "linear": {"base", "step"}, "exponential": {"base", "factor"}}[kind]
    extra = sorted(set(spec) - allowed)
    if extra:
        raise ConfigError(f"backoff: unexpected key(s) for {kind}: {', '.join(extra)}")
    jitter = spec.get("jitter", "none")
    if jitter not in JITTERS:
        raise ConfigError(f"backoff: jitter must be one of {', '.join(JITTERS)}")
    cap = None if spec.get("max") is None else _num(spec, "max")
    if kind == "fixed":
        return Backoff("fixed", base=_num(spec, "delay"), max=cap, jitter=jitter)
    if kind == "linear":
        return Backoff("linear", base=_num(spec, "base"), step=_num(spec, "step", 0), max=cap, jitter=jitter)
    factor = _num(spec, "factor", 2.0, minimum=1.0)
    return Backoff("exponential", base=_num(spec, "base"), factor=factor, max=cap, jitter=jitter)


def retry_delay(spec, attempt: int, job_id: str = "") -> float:
    return parse_backoff(spec).delay(attempt, job_id)
