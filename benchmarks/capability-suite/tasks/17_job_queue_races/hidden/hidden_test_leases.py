"""Lease ownership: a stale ack, nack or heartbeat must never win."""

import threading

import pytest

from hiddenkit import WAIT, Park, finish, make, outcome, run
from taskmill import LeaseLost, Registry, WorkerPool


def parked(broker, point, token=None):
    p = Park(lambda **kw: token is None or kw.get("token") == token)
    remove = broker.hooks.add(point, p)
    return p, remove


# ------------------------------------------------------------- ack vs expiry

def test_ack_loses_against_reap_while_parked():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve(worker="w1")
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, "late")
    assert p.entered.wait(WAIT)
    clock.advance(30)
    assert b.reap() == [r.job_id]
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    job = b.get(r.job_id)
    assert job.state == "pending" and job.result is None and job.attempts == 1


def test_ack_after_deadline_passed_while_parked_is_rejected_even_unreaped():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve(worker="w1")
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, "late")
    assert p.entered.wait(WAIT)
    clock.advance(30.5)
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    assert b.get(r.job_id).state in ("reserved", "pending")
    b.reap()
    job = b.get(r.job_id)
    assert job.state == "pending" and job.result is None and job.attempts == 1


def test_ack_loses_against_redelivery():
    b, clock = make()
    b.enqueue("q", "k", None)
    r1 = b.reserve(worker="w1")
    p, remove = parked(b, "ack.before_commit", r1.token)
    t = run(b.ack, r1.token, "from-w1")
    assert p.entered.wait(WAIT)
    clock.advance(31)
    r2 = b.reserve(worker="w2")
    assert r2.job_id == r1.job_id and r2.attempt == 2
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    assert b.get(r1.job_id).state == "reserved"
    b.ack(r2.token, "from-w2")
    res = b.result(r1.job_id)
    assert res.state == "done" and res.result == "from-w2" and res.attempts == 2


def test_ack_loses_against_cancel():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, 1)
    assert p.entered.wait(WAIT)
    assert b.cancel(r.job_id) is True
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    assert b.get(r.job_id).state == "cancelled"


def test_parked_ack_without_interference_succeeds():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, {"ok": 1})
    assert p.entered.wait(WAIT)
    clock.advance(29.9)
    p.release.set()
    finish(*t)
    remove()
    assert b.result(r.job_id).result == {"ok": 1}


def test_lost_ack_is_counted():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, 1)
    assert p.entered.wait(WAIT)
    clock.advance(31)
    b.reap()
    p.release.set()
    outcome(*t)
    remove()
    assert b.metrics.value("leases.lost", op="ack") == 1
    assert b.metrics.value("jobs.acked", queue="q") == 0


# ------------------------------------------------------------ nack vs expiry

def test_nack_loses_against_redelivery():
    b, clock = make()
    b.enqueue("q", "k", None)
    r1 = b.reserve(worker="w1")
    p, remove = parked(b, "nack.before_commit", r1.token)
    t = run(b.nack, r1.token, "provider timeout")
    assert p.entered.wait(WAIT)
    clock.advance(31)
    r2 = b.reserve(worker="w2")
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    job = b.get(r1.job_id)
    assert job.state == "reserved" and job.worker == "w2"
    assert b.heartbeat(r2.token) == clock() + 30
    b.ack(r2.token, "ok")
    assert b.result(r1.job_id).result == "ok"


def test_nack_loses_against_reap():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "nack.before_commit", r.token)
    t = run(b.nack, r.token, "boom")
    assert p.entered.wait(WAIT)
    clock.advance(30)
    b.reap()
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    job = b.get(r.job_id)
    assert job.state == "pending"
    assert [e["message"] for e in job.errors] == ["lease expired"]


def test_nack_on_last_attempt_loses_against_reap():
    b, clock = make()
    b.enqueue("q", "k", None, max_attempts=1)
    r = b.reserve()
    p, remove = parked(b, "nack.before_commit", r.token)
    t = run(b.nack, r.token, "boom", None, True)
    assert p.entered.wait(WAIT)
    clock.advance(30)
    b.reap()
    p.release.set()
    kind, val = outcome(*t)
    remove()
    assert kind == "error" and isinstance(val, LeaseLost)
    res = b.result(r.job_id)
    assert res.state == "failed" and res.error == "lease expired"


def test_lost_nack_is_counted_and_does_not_retry():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "nack.before_commit", r.token)
    t = run(b.nack, r.token, "x")
    assert p.entered.wait(WAIT)
    clock.advance(31)
    b.reserve()
    p.release.set()
    outcome(*t)
    remove()
    assert b.metrics.value("leases.lost", op="nack") == 1
    assert b.metrics.value("jobs.retried", queue="q") == 0


def test_parked_ack_does_not_block_other_operations():
    b, clock = make()
    b.enqueue("q", "k", None)
    r = b.reserve()
    p, remove = parked(b, "ack.before_commit", r.token)
    t = run(b.ack, r.token, 1)
    assert p.entered.wait(WAIT)
    other = run(lambda: (b.enqueue("q", "k", 2).job_id, b.reserve(worker="w9").job_id, b.stats()["jobs"]))
    try:
        got = finish(*other, timeout=5)
    finally:
        p.release.set()
    finish(*t)
    remove()
    assert got == ("job-2", "job-2", 2)


def test_durable_state_after_lost_ack_recovers(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    b.enqueue("q", "k", None)
    r1 = b.reserve(worker="w1")
    p, remove = parked(b, "ack.before_commit", r1.token)
    t = run(b.ack, r1.token, "w1")
    assert p.entered.wait(WAIT)
    clock.advance(31)
    r2 = b.reserve(worker="w2")
    p.release.set()
    outcome(*t)
    remove()
    b.ack(r2.token, "w2")
    fp = b.fingerprint()
    b.close()
    b2, _ = make(str(tmp_path / "d"), clock=clock)
    assert b2.fingerprint() == fp
    assert b2.result(r1.job_id).result == "w2"
    b2.close()


# ------------------------------------------------------------------ heartbeats

def _redelivered():
    b, clock = make()
    b.enqueue("q", "k", None)
    r1 = b.reserve(worker="w1")
    clock.advance(31)
    r2 = b.reserve(worker="w2")
    assert r2.job_id == r1.job_id
    return b, clock, r1, r2


def test_heartbeat_with_superseded_token_is_rejected():
    b, clock, r1, r2 = _redelivered()
    with pytest.raises(LeaseLost):
        b.heartbeat(r1.token)


def test_superseded_heartbeat_does_not_extend_new_lease():
    b, clock, r1, r2 = _redelivered()
    clock.advance(20)
    with pytest.raises(LeaseLost):
        b.heartbeat(r1.token)
    assert b.get(r2.job_id).lease_deadline == r2.deadline
    assert [l["deadline"] for l in b.leases()] == [r2.deadline]
    clock.advance(10)
    assert b.reap() == [r2.job_id]


def test_superseded_heartbeat_with_extend_rejected():
    b, clock, r1, r2 = _redelivered()
    with pytest.raises(LeaseLost):
        b.heartbeat(r1.token, extend=600)
    assert b.get(r2.job_id).lease_deadline == r2.deadline


def test_superseded_heartbeat_counted_and_not_committed():
    b, clock, r1, r2 = _redelivered()
    seq = b.last_seq
    with pytest.raises(LeaseLost):
        b.heartbeat(r1.token)
    assert b.last_seq == seq
    assert b.metrics.value("leases.lost", op="heartbeat") == 1
    assert b.metrics.value("leases.heartbeats") == 0


def test_heartbeat_after_ack_and_redelivery_chain():
    b, clock, r1, r2 = _redelivered()
    clock.advance(31)
    r3 = b.reserve(worker="w3")
    for tok in (r1.token, r2.token):
        with pytest.raises(LeaseLost):
            b.heartbeat(tok)
    assert b.heartbeat(r3.token) == clock() + 30
    with pytest.raises(LeaseLost):
        b.ack(r2.token, "w2")
    b.ack(r3.token, "w3")
    assert b.result(r3.job_id).result == "w3"


def test_current_heartbeat_still_works():
    b, clock, r1, r2 = _redelivered()
    clock.advance(10)
    assert b.heartbeat(r2.token) == clock() + 30
    assert b.metrics.value("leases.heartbeats") == 1


def test_superseded_heartbeat_in_wal_does_not_resurrect(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    b.enqueue("q", "k", None)
    r1 = b.reserve(worker="w1")
    clock.advance(31)
    r2 = b.reserve(worker="w2")
    with pytest.raises(LeaseLost):
        b.heartbeat(r1.token)
    fp = b.fingerprint()
    b.close()
    b2, _ = make(str(tmp_path / "d"), clock=clock)
    assert b2.fingerprint() == fp
    assert b2.get(r2.job_id).lease_deadline == r2.deadline
    b2.close()


def test_pool_heartbeat_marks_superseded_context_lost():
    b, clock = make()
    reg = Registry()
    started = threading.Event()
    go = threading.Event()
    seen = {}

    def slow(ctx):
        seen["ctx"] = ctx
        started.set()
        assert go.wait(WAIT)
        return "w1-result"

    reg.register("slow", slow)
    b.enqueue("q", "slow", None)
    pool = WorkerPool(b, reg, concurrency=1, poll=0.01, heartbeat_interval=3600).start()
    try:
        assert started.wait(WAIT)
        clock.advance(31)
        r2 = b.reserve(worker="other")
        assert r2 is not None
        assert pool.heartbeat_now() == 0
        assert seen["ctx"].lost
        assert b.get(r2.job_id).lease_deadline == r2.deadline
        go.set()
        for _ in range(500):
            if not pool.inflight():
                break
            threading.Event().wait(0.01)
        b.ack(r2.token, "w2-result")
    finally:
        go.set()
        pool.stop()
    assert b.result(r2.job_id).result == "w2-result"
    assert b.metrics.value("worker.handled", kind="slow", outcome="lost") == 1


# ----------------------------------------------------- end to end: "ran twice"

def test_pool_slow_ack_racing_redelivery_completes_once():
    b, clock = make()
    reg = Registry()
    second_started = threading.Event()
    second_go = threading.Event()

    def h(ctx):
        if ctx.attempt == 1:
            return "first"
        second_started.set()
        assert second_go.wait(WAIT)
        return "second"

    reg.register("send", h)
    p = Park(lambda **kw: True)
    remove = b.hooks.add("ack.before_commit", p)
    job_id = b.enqueue("q", "send", None).job_id
    pool = WorkerPool(b, reg, concurrency=2, poll=0.01, heartbeat_interval=3600).start()
    try:
        assert p.entered.wait(WAIT)          # attempt 1 is acking
        clock.advance(31)                    # ... and its lease runs out
        assert second_started.wait(WAIT)     # another worker got the job
        p.release.set()
        for _ in range(500):
            if b.metrics.value("worker.handled", kind="send", outcome="lost") or \
               b.metrics.value("worker.handled", kind="send", outcome="ok"):
                break
            threading.Event().wait(0.01)
        second_go.set()
        view = b.wait(job_id, timeout=WAIT)
    finally:
        p.release.set()
        second_go.set()
        pool.stop()
        remove()
    assert view is not None and view.state == "done"
    assert view.result == "second" and view.attempts == 2
    assert b.metrics.value("worker.handled", kind="send", outcome="ok") == 1
    assert b.metrics.value("worker.handled", kind="send", outcome="lost") == 1
    assert b.metrics.value("jobs.acked", queue="q") == 1
