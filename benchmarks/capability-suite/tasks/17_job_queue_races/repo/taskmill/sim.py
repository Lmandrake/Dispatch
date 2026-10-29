"""Capacity-planning simulator.

:func:`simulate` replays an arrival schedule against a real in-memory
:class:`~taskmill.broker.Broker` driven by a :class:`~taskmill.clock.ManualClock`,
with ``workers`` simulated workers that reserve, "run" for the arrival's
service time, and ack or nack. Nothing sleeps: the clock jumps from event to
event (next arrival, next worker completion, next retry becoming ready).

An :class:`Arrival` is ``(time, queue, kind, service_seconds, fail_prob)``. Each
delivery fails independently with probability ``fail_prob``, drawn from a
generator seeded with ``seed`` in reservation order, so a run is a pure
function of (arrivals, workers, config, seed). A failed delivery is nacked and
retried by the broker's backoff until ``max_attempts`` is used up.

The :class:`SimReport` holds throughput (jobs finished per simulated second
over the whole run), the mean and 95th-percentile queue wait (ready to
reserved, per delivery) and run time, retries and permanently failed jobs.
"""

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Sequence

from .backoff import parse_backoff
from .broker import Broker
from .clock import ManualClock
from .config import BrokerConfig
from .job import DELAYED, DONE, FAILED

EPOCH = 1_000_000.0


class Arrival(NamedTuple):
    time: float
    queue: str
    kind: str
    service_seconds: float
    fail_prob: float = 0.0


@dataclass
class SimReport:
    workers: int
    jobs: int
    done: int = 0
    failed: int = 0
    retries: int = 0
    duration: float = 0.0
    throughput: float = 0.0
    wait_mean: float = 0.0
    wait_p95: float = 0.0
    run_mean: float = 0.0
    run_p95: float = 0.0
    utilization: float = 0.0
    waits: List[float] = field(default_factory=list, repr=False)
    runs: List[float] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("workers", "jobs", "done", "failed", "retries", "duration",
                                              "throughput", "wait_mean", "wait_p95", "run_mean",
                                              "run_p95", "utilization")}

    def render(self) -> str:
        return "\n".join([
            f"workers      {self.workers}",
            f"jobs         {self.jobs} (done {self.done}, failed {self.failed}, retries {self.retries})",
            f"duration     {self.duration:.2f}s   throughput {self.throughput:.3f} jobs/s",
            f"wait         mean {self.wait_mean:.2f}s   p95 {self.wait_p95:.2f}s",
            f"run          mean {self.run_mean:.2f}s   p95 {self.run_p95:.2f}s",
            f"utilization  {self.utilization * 100:.1f}%",
        ])


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[rank - 1]


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def make_arrivals(count: int, rate: float, queue: str = "default", kind: str = "work",
                  service_seconds: float = 1.0, fail_prob: float = 0.0, seed: int = 0) -> List[Arrival]:
    """A Poisson arrival stream: ``count`` jobs at ``rate`` per second."""
    rng = random.Random(seed)
    t, out = 0.0, []
    for _ in range(count):
        t += rng.expovariate(rate)
        out.append(Arrival(round(t, 6), queue, kind, service_seconds, fail_prob))
    return out


@dataclass
class _Busy:
    finish: float
    worker: int
    token: str
    started: float
    fail: bool


def _config(arrivals: Sequence[Arrival], max_attempts: int, backoff: dict) -> BrokerConfig:
    longest = max((a.service_seconds for a in arrivals), default=1.0)
    timeout = max(30.0, longest * 2 + 1)
    return BrokerConfig(visibility_timeout=timeout, max_visibility_timeout=max(3600.0, timeout),
                        max_attempts=max_attempts, backoff=parse_backoff(backoff).to_dict())


def simulate(arrivals: Sequence[Arrival], workers: int = 4, seed: int = 0, max_attempts: int = 3,
             backoff: Optional[dict] = None) -> SimReport:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    schedule = sorted(arrivals, key=lambda a: a.time)
    clock = ManualClock(EPOCH)
    broker = Broker(None, _config(schedule, max_attempts, backoff or {"kind": "fixed", "delay": 1.0}),
                    clock=clock)
    rng = random.Random(seed)
    report = SimReport(workers=workers, jobs=len(schedule))
    busy: Dict[int, _Busy] = {}
    spec_of: Dict[str, Arrival] = {}
    nxt = 0
    busy_time = 0.0
    now = EPOCH
    try:
        while True:
            while nxt < len(schedule) and EPOCH + schedule[nxt].time <= now:
                a = schedule[nxt]
                spec_of[broker.enqueue(a.queue, a.kind, {"n": nxt}).job_id] = a
                nxt += 1
            for w in sorted(w for w, b in busy.items() if b.finish <= now):
                busy_time += _complete(broker, report, busy.pop(w))
            for w in range(workers):
                if w in busy:
                    continue
                started = _start(broker, rng, report, spec_of, w, now)
                if started is None:
                    break
                busy[w] = started
            upcoming = _next_event(broker, schedule, nxt, busy, now)
            if upcoming is None:
                break
            now = upcoming
            clock.set(now)
        _finalize(broker, report, now - EPOCH, busy_time, schedule)
    finally:
        broker.close()
    return report


def _start(broker, rng, report: SimReport, spec_of: Dict[str, Arrival], worker: int,
           now: float) -> Optional[_Busy]:
    res = broker.reserve(worker=f"sim-{worker}")
    if res is None:
        return None
    spec = spec_of[res.job_id]
    job = broker.get(res.job_id)
    report.waits.append(max(0.0, broker.clock() - job.ready_at))
    fail = rng.random() < spec.fail_prob
    return _Busy(now + spec.service_seconds, worker, res.token, now, fail)


def _complete(broker, report: SimReport, b: _Busy) -> float:
    run = b.finish - b.started
    report.runs.append(run)
    if b.fail:
        if broker.nack(b.token, "simulated failure") == DELAYED:
            report.retries += 1
    else:
        broker.ack(b.token)
    return run


def _next_event(broker, schedule, nxt: int, busy: Dict[int, _Busy], now: float) -> Optional[float]:
    times = [b.finish for b in busy.values()]
    if nxt < len(schedule):
        times.append(EPOCH + schedule[nxt].time)
    times.extend(j.run_at for j in broker.jobs(state=DELAYED))
    later = [t for t in times if t > now]
    return min(later) if later else None


def _finalize(broker, report: SimReport, end: float, busy_time: float, schedule) -> None:
    report.done = len(broker.jobs(state=DONE))
    report.failed = len(broker.jobs(state=FAILED))
    start = schedule[0].time if schedule else 0.0
    report.duration = max(0.0, end - start)
    report.throughput = (report.done + report.failed) / report.duration if report.duration else 0.0
    report.wait_mean, report.wait_p95 = mean(report.waits), percentile(report.waits, 95)
    report.run_mean, report.run_p95 = mean(report.runs), percentile(report.runs, 95)
    capacity = report.duration * report.workers
    report.utilization = min(1.0, busy_time / capacity) if capacity else 0.0
