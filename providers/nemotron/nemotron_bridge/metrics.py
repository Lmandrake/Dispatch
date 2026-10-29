"""Performance metrics: latency, velocity, and empirical max rate.

Metric vocabulary follows NVIDIA GenAI-Perf conventions:
  * TTFT  — time to first token (s)
  * decode rate — output tokens / sec during generation (velocity)
  * request latency — total wall time (s)
  * max rate — empirically probed requests/min before rate limiting kicks in
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from .client import ChatResult, NemotronClient

_PERF_PROMPT = [
    {"role": "user", "content": "Write a haiku about distributed systems."}
]


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def _p90(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    idx = min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))
    return round(xs[idx], 3)


@dataclass
class PerfSummary:
    model: str
    runs: int = 0
    ok: int = 0
    ttft_median: float | None = None
    ttft_p90: float | None = None
    latency_median: float | None = None
    tokens_per_sec_median: float | None = None
    tokens_per_sec_p90: float | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["errors"] = self.errors[:5]
        return d


def measure_perf(
    client: NemotronClient,
    model: str,
    repeats: int = 3,
    max_tokens: int = 512,
) -> PerfSummary:
    """Run the same short prompt N times; aggregate streaming timings.

    Velocity is measured over generated tokens whether or not they are hidden
    reasoning tokens, so reasoning models are timed fairly.
    """
    results: list[ChatResult] = []
    for _ in range(repeats):
        results.append(
            client.chat(model, _PERF_PROMPT, max_tokens=max_tokens, stream=True)
        )
    ok = [r for r in results if r.ok and r.tokens_per_sec is not None]
    return PerfSummary(
        model=model,
        runs=len(results),
        ok=len(ok),
        ttft_median=_median([r.ttft for r in ok]),
        ttft_p90=_p90([r.ttft for r in ok]),
        latency_median=_median([r.latency for r in ok]),
        tokens_per_sec_median=_median([r.tokens_per_sec for r in ok]),
        tokens_per_sec_p90=_p90([r.tokens_per_sec for r in ok]),
        errors=[r.error for r in results if r.error],
    )


@dataclass
class RateProbe:
    model: str
    burst: int
    elapsed: float
    successes: int
    rate_limited: int
    other_errors: int
    effective_rpm: float | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def probe_max_rate(
    model: str,
    burst: int = 12,
    max_tokens: int = 8,
) -> RateProbe:
    """Fire a burst of tiny requests back-to-back (no client limiter) and count
    how many succeed vs. hit 429, to empirically characterize the rate cap.

    Uses a dedicated unthrottled client so we actually reach the limit.
    """
    unlimited = NemotronClient(rpm=100_000)
    prompt = [{"role": "user", "content": "ok"}]
    successes = rate_limited = other = 0
    start = time.monotonic()
    for _ in range(burst):
        r = unlimited.chat(model, prompt, max_tokens=max_tokens, stream=False)
        if r.ok:
            successes += 1
        elif r.error and ("429" in r.error or "RateLimit" in r.error):
            rate_limited += 1
        else:
            other += 1
    elapsed = time.monotonic() - start
    eff = round(successes / elapsed * 60, 1) if elapsed > 0 else None
    return RateProbe(
        model=model,
        burst=burst,
        elapsed=round(elapsed, 2),
        successes=successes,
        rate_limited=rate_limited,
        other_errors=other,
        effective_rpm=eff,
    )
