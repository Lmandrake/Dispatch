"""Cron calendars, decorrelated jitter, cancel races, checkpoints, pool shutdown,
expiry on the last attempt, and the result cache."""

import calendar
import os
import threading

import pytest

from hiddenkit import WAIT, Park, finish, make, run
from taskmill import LeaseLost, Registry, WorkerPool, parse_backoff
from taskmill.cron import format_slot, parse_cron
from taskmill.resultcache import CachedSubmitter


def ts(*ymd_hm):
    y, mo, d, h, mi = (list(ymd_hm) + [0, 0])[:5]
    return float(calendar.timegm((y, mo, d, h, mi, 0)))


def wait_until(pred, timeout=WAIT):
    ev = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if pred():
            return True
        ev.wait(0.01)
    return pred()


# ===================================================================== cron

@pytest.mark.parametrize("after,want", [
    (ts(2099, 6, 1), "2104-02-29T00:00"),
    (ts(2100, 1, 1), "2104-02-29T00:00"),
    (ts(1999, 6, 1), "2000-02-29T00:00"),
    (ts(2023, 3, 1), "2024-02-29T00:00"),
])
def test_feb_29_only_in_gregorian_leap_years(after, want):
    assert format_slot(parse_cron("0 0 29 2 *").next_after(after)) == want


def test_monthly_29th_skips_february_2100():
    e = parse_cron("0 2 29 * *")
    got = [format_slot(t) for t in e.upcoming(ts(2100, 1, 15), 3)]
    assert got == ["2100-01-29T02:00", "2100-03-29T02:00", "2100-04-29T02:00"]


def test_last_day_fields_across_month_ends():
    e = parse_cron("0 3 31 * *")
    got = [format_slot(t) for t in e.upcoming(ts(2026, 1, 1), 7)]
    assert got == ["2026-01-31T03:00", "2026-03-31T03:00", "2026-05-31T03:00", "2026-07-31T03:00",
                   "2026-08-31T03:00", "2026-10-31T03:00", "2026-12-31T03:00"]
    e30 = parse_cron("0 0 30 * *")
    assert [format_slot(t) for t in e30.upcoming(ts(2100, 1, 1), 2)] == ["2100-01-30T00:00", "2100-03-30T00:00"]


def test_feb_30_never_matches():
    from taskmill.errors import CronError
    with pytest.raises(CronError):
        parse_cron("0 0 30 2 *").next_after(0)


def test_weekday_matching_in_2100():
    e = parse_cron("0 12 * * mon")       # 2100-03-01 is a Monday
    assert format_slot(e.next_after(ts(2100, 2, 27))) == "2100-03-01T12:00"
    assert e.matches(ts(2100, 3, 1, 12, 0)) and not e.matches(ts(2100, 2, 28, 12, 0))


def test_scheduler_cron_slots_in_century_year():
    from taskmill import Schedule, Scheduler
    b, _ = make()
    s = Scheduler(b, [Schedule("leap", "q", "echo", cron="0 0 29 * *", max_catchup=5)], start_at=ts(2100, 1, 1))
    fired = s.tick(now=ts(2100, 4, 1))
    assert [format_slot(f.slot) for f in fired] == ["2100-01-29T00:00", "2100-03-29T00:00"]


# ================================================================== backoff

@pytest.mark.parametrize("job_id", [f"job-{i}" for i in range(1, 9)])
def test_decorrelated_jitter_never_exceeds_max(job_id):
    b = parse_backoff({"kind": "exponential", "base": 2, "factor": 2, "max": 30, "jitter": "decorrelated"})
    delays = b.schedule(25, job_id)
    assert all(2 <= d <= 30 for d in delays), delays


def test_decorrelated_cap_feeds_next_step():
    import random
    from taskmill.backoff import _seed
    b = parse_backoff({"kind": "exponential", "base": 1, "max": 5, "jitter": "decorrelated"})
    prev = 1.0
    want = []
    for a in range(1, 15):
        prev = min(5.0, random.Random(_seed("job-7", a)).uniform(1.0, max(1.0, prev * 3)))
        want.append(prev)
    assert b.schedule(14, "job-7") == pytest.approx(want)


def test_decorrelated_through_broker_respects_max():
    b, clock = make(backoff={"kind": "exponential", "base": 2, "factor": 2, "max": 30, "jitter": "decorrelated"},
                    max_attempts=40)
    jid = b.enqueue("q", "k").job_id
    for _ in range(20):
        r = b.reserve()
        b.nack(r.token, "e")
        j = b.get(jid)
        assert j.run_at - clock() <= 30
        clock.advance(j.run_at - clock())


def test_other_jitters_unchanged():
    b = parse_backoff({"kind": "exponential", "base": 1, "factor": 2, "max": 10, "jitter": "full"})
    assert all(0 <= d <= 10 for d in b.schedule(10, "job-3"))
    assert parse_backoff({"kind": "exponential", "base": 1, "factor": 2, "max": 10}).schedule(6) == [1, 2, 4, 8, 10, 10]


# ============================================================ cancel races

def _park_cancel(b):
    p = Park()
    remove = b.hooks.add("cancel.before_commit", p)
    return p, remove


def test_cancel_racing_reserve_ends_the_new_lease():
    b, clock = make()
    jid = b.enqueue("q", "k").job_id
    p, remove = _park_cancel(b)
    t = run(b.cancel, jid)
    assert p.entered.wait(WAIT)
    r = b.reserve(worker="w")
    assert r.job_id == jid
    p.release.set()
    assert finish(*t) is True
    remove()
    assert b.get(jid).state == "cancelled"
    assert b.leases() == []
    with pytest.raises(LeaseLost):
        b.ack(r.token, "shipped")
    with pytest.raises(LeaseLost):
        b.heartbeat(r.token)
    assert b.reserve() is None


def test_cancel_racing_ack_reports_false():
    b, clock = make()
    jid = b.enqueue("q", "k").job_id
    r = b.reserve()
    p, remove = _park_cancel(b)
    t = run(b.cancel, jid)
    assert p.entered.wait(WAIT)
    b.ack(r.token, "done-first")
    p.release.set()
    assert finish(*t) is False
    remove()
    res = b.result(jid)
    assert res.state == "done" and res.result == "done-first"
    assert b.metrics.value("jobs.cancelled", queue="q") == 0


def test_cancel_racing_reserve_recovers(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    jid = b.enqueue("q", "k").job_id
    p, remove = _park_cancel(b)
    t = run(b.cancel, jid)
    assert p.entered.wait(WAIT)
    b.reserve()
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    b2, _ = make(str(tmp_path / "d"), clock=clock)
    assert b2.fingerprint() == fp and b2.leases() == []
    b2.close()


def test_cancel_racing_reserve_pool_keeps_working():
    b, clock = make()
    reg = Registry()
    started = threading.Event()
    go = threading.Event()

    def h(ctx):
        if ctx.payload == "slow":
            started.set()
            assert go.wait(WAIT)
        return ctx.payload

    reg.register("h", h)
    jid = b.enqueue("q", "h", "slow").job_id
    p, remove = _park_cancel(b)
    t = run(b.cancel, jid)
    assert p.entered.wait(WAIT)
    pool = WorkerPool(b, reg, concurrency=1, poll=0.01, heartbeat_interval=3600).start()
    try:
        assert started.wait(WAIT)
        p.release.set()
        finish(*t)
        go.set()
        other = b.enqueue("q", "h", "next").job_id
        view = b.wait(other, timeout=WAIT)
    finally:
        p.release.set()
        go.set()
        pool.stop()
        remove()
    assert view is not None and view.result == "next"
    assert b.get(jid).state == "cancelled"
    assert b.metrics.value("worker.handled", kind="h", outcome="lost") == 1


# ============================================================== checkpoints

def test_change_during_checkpoint_survives_restart(tmp_path):
    path = str(tmp_path / "d")
    b, clock = make(path)
    b.enqueue("q", "k", "before")
    p = Park()
    remove = b.hooks.add("checkpoint.begin", p)
    t = run(b.checkpoint)
    assert p.entered.wait(WAIT)
    late = b.enqueue("q", "k", "during").job_id
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    b2, _ = make(path, clock=clock)
    assert b2.fingerprint() == fp
    assert b2.get(late).payload == "during"
    assert b2.enqueue("q", "k").job_id == "job-3"
    b2.close()


def test_ack_and_heartbeat_during_checkpoint_survive(tmp_path):
    path = str(tmp_path / "d")
    b, clock = make(path)
    b.enqueue("q", "k")
    b.enqueue("q", "k")
    r1 = b.reserve()
    r2 = b.reserve()
    p = Park()
    remove = b.hooks.add("checkpoint.begin", p)
    t = run(b.checkpoint)
    assert p.entered.wait(WAIT)
    b.ack(r1.token, "acked-during")
    d = b.heartbeat(r2.token, extend=500)
    p.release.set()
    finish(*t)
    remove()
    b.close()
    b2, _ = make(path, clock=clock)
    assert b2.result(r1.job_id).result == "acked-during"
    assert b2.get(r2.job_id).lease_deadline == d
    b2.close()


def test_snapshot_position_matches_its_content(tmp_path):
    from taskmill import snapshot as snapmod
    path = str(tmp_path / "d")
    b, clock = make(path)
    b.enqueue("q", "k")
    p = Park()
    remove = b.hooks.add("checkpoint.begin", p)
    t = run(b.checkpoint)
    assert p.entered.wait(WAIT)
    b.enqueue("q", "k")
    b.enqueue("q", "k")
    p.release.set()
    snap_path = finish(*t)
    remove()
    snap = snapmod.read_snapshot(snap_path)
    assert snap.last_seq == len(snap.jobs) == 1
    b.close()


def test_checkpoint_without_interference_unchanged(tmp_path):
    path = str(tmp_path / "d")
    b, clock = make(path)
    for i in range(4):
        b.enqueue("q", "k", i)
    assert os.path.basename(b.checkpoint()) == "snapshot-000000000004.json"
    b.close()


# ============================================================= pool shutdown

def test_pool_stop_gives_back_prefetched_jobs():
    b, clock = make()
    reg = Registry()
    started = threading.Event()
    go = threading.Event()

    def h(ctx):
        started.set()
        assert go.wait(WAIT)
        return ctx.payload

    reg.register("h", h)
    ids = [b.enqueue("q", "h", i).job_id for i in range(5)]
    pool = WorkerPool(b, reg, concurrency=1, prefetch=4, poll=0.01, heartbeat_interval=3600).start()
    assert started.wait(WAIT)
    assert wait_until(lambda: len(b.leases()) == 4)
    stopper = run(pool.stop)
    go.set()
    finish(*stopper)
    states = [b.get(i).state for i in ids]
    assert states == ["done", "pending", "pending", "pending", "pending"]
    assert [b.get(i).attempts for i in ids] == [1, 0, 0, 0, 0]
    assert b.leases() == []
    assert [b.reserve().job_id for _ in range(4)] == ids[1:]


def test_pool_stop_completes_started_handlers():
    b, clock = make()
    reg = Registry()
    barrier = threading.Barrier(3, timeout=WAIT)
    reg.register("h", lambda ctx: barrier.wait() and "ok" or "ok")
    ids = [b.enqueue("q", "h").job_id for _ in range(2)]
    pool = WorkerPool(b, reg, concurrency=2, poll=0.01, heartbeat_interval=3600).start()
    assert wait_until(lambda: len(b.leases()) == 2)
    stopper = run(pool.stop)
    barrier.wait()
    finish(*stopper)
    assert [b.get(i).state for i in ids] == ["done", "done"]
    assert b.metrics.value("worker.handled", kind="h", outcome="ok") == 2


def test_pool_stop_max_attempts_one_not_burned():
    b, clock = make()
    reg = Registry()
    started = threading.Event()
    go = threading.Event()
    reg.register("h", lambda ctx: started.set() or go.wait(WAIT))
    b.enqueue("q", "h")
    rest = [b.enqueue("q", "h", max_attempts=1).job_id for _ in range(2)]
    pool = WorkerPool(b, reg, concurrency=1, prefetch=3, poll=0.01, heartbeat_interval=3600).start()
    assert started.wait(WAIT)
    assert wait_until(lambda: len(b.leases()) == 3)
    stopper = run(pool.stop)
    go.set()
    finish(*stopper)
    clock.advance(31)
    b.reap()
    assert [b.get(i).state for i in rest] == ["pending", "pending"]


def test_release_api():
    b, clock = make()
    jid = b.enqueue("q", "k").job_id
    r = b.reserve()
    b.release(r.token)
    j = b.get(jid)
    assert j.state == "pending" and j.attempts == 0
    with pytest.raises(LeaseLost):
        b.release(r.token)


# ===================================================== expiry, last attempt

def test_expiry_on_last_attempt_fails_job():
    b, clock = make()
    jid = b.enqueue("q", "k", max_attempts=3).job_id
    for n in range(1, 4):
        r = b.reserve()
        assert r.attempt == n
        clock.advance(30)
        b.reap()
    res = b.result(jid)
    assert res.state == "failed" and res.attempts == 3 and res.error == "lease expired"
    assert b.reserve() is None
    assert b.metrics.value("jobs.failed", queue="q") == 1


def test_expiry_single_attempt():
    b, clock = make()
    jid = b.enqueue("q", "k", max_attempts=1).job_id
    b.reserve()
    clock.advance(30)
    assert b.reap() == [jid]
    assert b.get(jid).state == "failed"


def test_expiry_inline_on_reserve_last_attempt():
    b, clock = make()
    jid = b.enqueue("q", "k", max_attempts=2).job_id
    b.reserve()
    clock.advance(30)
    assert b.reserve().attempt == 2
    clock.advance(30)
    assert b.reserve() is None
    assert b.get(jid).state == "failed"


def test_mixed_nack_then_expiry_counts_attempts():
    b, clock = make(max_attempts=2, backoff={"kind": "fixed", "delay": 0})
    jid = b.enqueue("q", "k").job_id
    r = b.reserve()
    b.nack(r.token, "e")
    b.reserve()
    clock.advance(30)
    b.reap()
    assert b.get(jid).state == "failed" and b.get(jid).attempts == 2


# ============================================================ result cache

def _cache():
    b, clock = make()
    return b, clock, CachedSubmitter(b, kinds=["render"], ttl=600)


def _complete(b, result):
    r = b.reserve()
    b.ack(r.token, result)
    return r


def test_result_cache_does_not_cross_tenants():
    b, clock, c = _cache()
    s1 = c.submit("reports", "render", {"month": "2026-09"}, tenant="acme")
    _complete(b, {"pdf": "acme-statement"})
    c.collect()
    s2 = c.submit("reports", "render", {"month": "2026-09"}, tenant="globex")
    assert not s2.cached and s2.job_id is not None and s2.job_id != s1.job_id
    assert b.get(s2.job_id).tenant == "globex"


def test_result_cache_same_tenant_hits():
    b, clock, c = _cache()
    c.submit("reports", "render", {"month": "2026-09", "fmt": "pdf"}, tenant="acme")
    r = _complete(b, {"pdf": "x"})
    c.collect()
    s = c.submit("reports", "render", {"fmt": "pdf", "month": "2026-09"}, tenant="acme")
    assert s.cached and s.result == {"pdf": "x"} and s.source_job == r.job_id
    assert b.metrics.value("resultcache.hits", kind="render") == 1


def test_result_cache_no_tenant_vs_tenant():
    b, clock, c = _cache()
    c.submit("reports", "render", {"m": 1})
    _complete(b, "shared")
    c.collect()
    assert not c.submit("reports", "render", {"m": 1}, tenant="acme").cached
    assert c.submit("reports", "render", {"m": 1}).cached


def test_result_cache_invalidate_per_tenant():
    b, clock, c = _cache()
    for t in ("acme", "globex"):
        c.submit("reports", "render", {"m": 1}, tenant=t)
        _complete(b, t)
    c.collect()
    assert c.invalidate("reports", "render", {"m": 1}, tenant="acme") is True
    assert not c.submit("reports", "render", {"m": 1}, tenant="acme").cached
    g = c.submit("reports", "render", {"m": 1}, tenant="globex")
    assert g.cached and g.result == "globex"


def test_result_cache_ttl_and_failures():
    b, clock, c = _cache()
    c.submit("reports", "render", {"m": 1}, tenant="a")
    r = b.reserve()
    b.nack(r.token, "x", permanent=True)
    c.collect()
    assert not c.submit("reports", "render", {"m": 1}, tenant="a").cached
    _complete(b, "ok")
    c.collect()
    clock.advance(599)
    assert c.submit("reports", "render", {"m": 1}, tenant="a").cached
    clock.advance(1)
    assert not c.submit("reports", "render", {"m": 1}, tenant="a").cached
