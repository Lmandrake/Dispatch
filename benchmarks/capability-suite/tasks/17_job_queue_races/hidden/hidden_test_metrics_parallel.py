"""Exact metrics, and the design constraints: no global serialisation."""

import sys
import threading

import pytest

from hiddenkit import WAIT, BarrierClock, Park, finish, make, run
from taskmill import Broker, BrokerConfig, Metrics, Registry, WorkerPool

# ================================================================== metrics

def test_counter_inc_does_not_lose_updates():
    m = Metrics(clock=BarrierClock())
    ts = [run(m.inc, "jobs.acked", 1, queue="q"), run(m.inc, "jobs.acked", 2, queue="q")]
    for t in ts:
        finish(*t)
    assert m.value("jobs.acked", queue="q") == 3
    assert m.counter("jobs.acked").last_updated(queue="q") == 42.0


def test_counter_unlabelled_does_not_lose_updates():
    m = Metrics(clock=BarrierClock())
    c = m.counter("wal.records")
    ts = [run(c.inc, 5), run(c.inc, 7)]
    for t in ts:
        finish(*t)
    assert c.get() == 12 and c.total() == 12


def test_histogram_observe_does_not_lose_updates():
    m = Metrics(clock=BarrierClock())
    h = m.histogram("worker.run_seconds")
    ts = [run(h.observe, 0.002), run(h.observe, 3.0)]
    for t in ts:
        finish(*t)
    assert h.count == 2 and h.sum == pytest.approx(3.002) and h.max == 3.0
    snap = m.snapshot("worker")
    assert snap["worker.run_seconds.count"] == 2
    assert snap["worker.run_seconds.le_0.005"] == 1 and snap["worker.run_seconds.le_5"] == 2


def test_metrics_hammer_exact():
    m = Metrics()
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        def work(i):
            for j in range(2000):
                m.inc("a")
                m.inc("b", 2, queue=f"q{i % 3}")
                m.observe("lat", float(j % 5))
        ts = [run(work, i) for i in range(8)]
        for t in ts:
            finish(*t)
    finally:
        sys.setswitchinterval(old)
    assert m.value("a") == 16000
    assert m.counter("b").total() == 32000
    snap = m.snapshot()
    assert snap["lat.count"] == 16000 and snap["lat.sum"] == 8 * sum(float(j % 5) for j in range(2000))
    assert snap["lat.max"] == 4.0 and snap["lat.le_5"] == 16000


def test_metrics_api_regression():
    from taskmill import ManualClock
    clock = ManualClock(5)
    m = Metrics(clock=clock)
    m.inc("x", queue="a")
    clock.advance(1)
    m.inc("x", 4, queue="a")
    m.gauge("g").set(3, queue="z")
    assert m.value("x", queue="a") == 5 and m.value("x", queue="b") == 0 and m.value("nope") == 0
    assert m.counter("x").last_updated(queue="a") == 6 and m.counter("x").last_updated(queue="q") is None
    assert m.snapshot() == {"g{queue=z}": 3, "x{queue=a}": 5}
    assert m.snapshot("x") == {}
    with pytest.raises(ValueError):
        m.inc("x", -1)
    assert m.render_text() == "g{queue=z} 3\nx{queue=a} 5\n"
    m.reset()
    assert m.value("x", queue="a") == 0


def test_broker_counters_exact_under_worker_pool():
    b = Broker(None, BrokerConfig(visibility_timeout=60))
    reg = Registry()
    reg.register("noop", lambda ctx: ctx.payload)
    n = 1500
    for i in range(n):
        b.enqueue(f"q{i % 3}", "noop", i)
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        with WorkerPool(b, reg, concurrency=8, poll=0.005, heartbeat_interval=3600) as pool:
            assert pool.drain(timeout=60)
    finally:
        sys.setswitchinterval(old)
    assert sum(b.metrics.value("jobs.acked", queue=f"q{k}") for k in range(3)) == n
    assert sum(b.metrics.value("jobs.reserved", queue=f"q{k}") for k in range(3)) == n
    assert b.metrics.value("worker.handled", kind="noop", outcome="ok") == n
    assert b.metrics.histogram("worker.run_seconds").count == n
    assert b.stats()["states"]["done"] == n


# ============================================ parallelism must be preserved

def test_handlers_run_in_parallel():
    b = Broker(None, BrokerConfig(visibility_timeout=60))
    reg = Registry()
    barrier = threading.Barrier(3, timeout=WAIT)
    reg.register("meet", lambda ctx: barrier.wait())
    ids = [b.enqueue("q", "meet").job_id for _ in range(3)]
    with WorkerPool(b, reg, concurrency=3, poll=0.01, heartbeat_interval=3600) as pool:
        assert pool.drain(timeout=WAIT)
    assert all(b.result(i).ok for i in ids)


def test_stalled_wal_write_does_not_block_other_operations(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    b.enqueue("q", "k", "first")
    p = Park(lambda record, **_: record["op"] == "enqueue" and record["job"]["payload"] == "slow")
    remove = b.hooks.add("wal.append", p)
    t = run(b.enqueue, "q", "k", "slow")
    assert p.entered.wait(WAIT)
    other = run(lambda: (b.reserve(worker="w").payload, b.stats()["jobs"], b.enqueue("z", "k", "z").job_id))
    try:
        got = finish(*other, timeout=5)
    finally:
        p.release.set()
    finish(*t)
    remove()
    assert got[0] == "first" and got[1] == 2 and got[2] == "job-3"
    b.close()


def test_slow_ack_encoding_point_does_not_block_reserve():
    b, clock = make()
    b.enqueue("q", "k", 1)
    b.enqueue("q", "k", 2)
    r = b.reserve()
    p = Park()
    remove = b.hooks.add("ack.before_commit", p)
    t = run(b.ack, r.token, "x")
    assert p.entered.wait(WAIT)
    other = run(b.reserve, "w2")
    try:
        got = finish(*other, timeout=5)
    finally:
        p.release.set()
    finish(*t)
    remove()
    assert got.payload == 2


def test_heartbeat_hook_can_call_back_into_broker():
    b, clock = make()
    b.enqueue("q", "k")
    r = b.reserve()
    seen = []
    remove = b.hooks.add("heartbeat", lambda **kw: seen.append(b.get(kw["job_id"]).lease_deadline))
    t = run(b.heartbeat, r.token)
    d = finish(*t, timeout=5)
    remove()
    assert seen == [d]
