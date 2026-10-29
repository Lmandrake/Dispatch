"""Per-queue rate limits (token buckets).

A queue configured with ``rate`` (reservations per second) and ``burst``
holds at most ``burst`` tokens, refilled continuously at ``rate`` per second
by the broker's clock. Each reservation from the queue takes one token; a
queue with no token is skipped by ``reserve`` as if it were empty (its jobs
stay pending, in order). Buckets start full.

Rate limits are runtime state only: they are not persisted, and a restarted
broker starts with full buckets.
"""

from typing import Dict, Optional


class TokenBucket:
    def __init__(self, rate: float, burst: int, now: float):
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self.rate = float(rate)
        self.burst = int(burst)
        self._tokens = float(burst)
        self._at = now

    def _refill(self, now: float) -> None:
        if now > self._at:
            self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
            self._at = now

    def available(self, now: float) -> float:
        self._refill(now)
        return self._tokens

    def try_take(self, now: float) -> bool:
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def next_token_at(self, now: float) -> float:
        """When the next whole token will be available."""
        self._refill(now)
        if self._tokens >= 1.0:
            return now
        return now + (1.0 - self._tokens) / self.rate


class RateLimits:
    """The buckets for every rate-limited queue. Not thread-safe: the broker lock guards it."""

    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}

    def configure(self, queue: str, rate: Optional[float], burst: int, now: float) -> None:
        if rate is None:
            self._buckets.pop(queue, None)
        else:
            self._buckets[queue] = TokenBucket(rate, burst, now)

    def limited(self, queue: str) -> bool:
        return queue in self._buckets

    def allows(self, queue: str, now: float) -> bool:
        b = self._buckets.get(queue)
        return b is None or b.available(now) >= 1.0

    def take(self, queue: str, now: float) -> None:
        b = self._buckets.get(queue)
        if b is not None and not b.try_take(now):
            raise RuntimeError(f"rate limit for {queue} exhausted")

    def next_token_at(self, queue: str, now: float) -> Optional[float]:
        b = self._buckets.get(queue)
        return None if b is None else b.next_token_at(now)

    def describe(self) -> Dict[str, Dict[str, float]]:
        return {q: {"rate": b.rate, "burst": b.burst} for q, b in sorted(self._buckets.items())}
