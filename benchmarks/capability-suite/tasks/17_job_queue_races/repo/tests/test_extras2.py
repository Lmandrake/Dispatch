import json
import os
import threading

import pytest

from taskmill import Broker, BrokerConfig, ManualClock, Runtime
from taskmill.archive import Archive, day_of
from taskmill.audit import AuditedBroker, AuditLog
from taskmill.batching import EnqueueBatcher
from taskmill.chaos import Chaos, InjectedFault
from taskmill.errors import Retry
from taskmill.healthcheck import FAIL, OK, WARN, Thresholds, check, liveness, readiness
from taskmill.mutex import MutexBusy, MutexLost, MutexManager, ctx_lock, exclusive
from taskmill.top import Dashboard, QueueRow, collect, render, sort_queues, truncate


def finish(broker, kind="k", queue="q"):
    jid = broker.enqueue(queue, kind).job_id
    broker.ack(broker.reserve("w").token)
    return jid


# ---------------------------------------------------------------- archive extras

def test_archive_stats_prune_export(broker, clock, tmp_path):
    arc = Archive(str(tmp_path / "arc"))
    for day in range(3):
        finish(broker, kind="a" if day else "b")
        arc.add(broker.jobs(state="done"))
        clock.advance(86400)
    st = arc.stats()
    assert st["files"] == 3 and st["jobs"] == 3 and st["by_kind"] == {"a": 2, "b": 1}
    assert st["first_day"] < st["last_day"] and st["bytes"] > 0
    assert [f.jobs for f in arc.files()] == [1, 1, 1]
    out = tmp_path / "out.jsonl"
    assert arc.export_jsonl(str(out), kind="b") == 1
    assert json.loads(out.read_text().splitlines()[0])["kind"] == "b"
    oldest = arc.days()[0]
    assert arc.prune_keep_days(2) == [oldest] and len(arc.days()) == 2
    assert arc.prune_older_than("9999-01-01") and arc.days() == []
    with pytest.raises(ValueError):
        arc.prune_keep_days(0)


# ---------------------------------------------------------------- audit extras

def test_audit_rotation_and_report(broker, clock, tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"), clock=clock, max_bytes=300, keep=2)
    ab = AuditedBroker(broker, log, actor="ann")
    for _ in range(12):
        ab.pause("q")
        clock.advance(1)
    assert len(log.files()) == 3 and os.path.getsize(log.path) <= 300
    assert all(os.path.getsize(p) <= 300 for p in log.files())
    entries = list(log.entries())
    assert [e.at for e in entries] == sorted(e.at for e in entries)
    start = entries[-1].at - 2
    assert len(log.between(start, start + 2)) == 2
    AuditedBroker(broker, log, actor="bo").resume("q")
    assert log.actors()["bo"] == 1
    text = log.report()
    assert "ann:" in text and "bo: resume x1" in text and "audit: " in text
    empty = AuditLog(str(tmp_path / "none.jsonl"))
    assert empty.report() == "audit: no entries\n"


# ---------------------------------------------------------------- top extras

def test_top_sort_truncate_json(broker, clock):
    broker.enqueue("alpha", "k")
    for _ in range(3):
        broker.enqueue("beta", "k")
    clock.advance(30)
    rows = collect(broker).queues
    assert [r.name for r in sort_queues(rows, "pending")] == ["beta", "alpha"]
    assert [r.name for r in sort_queues(rows, "name", descending=True)] == ["beta", "alpha"]
    assert sort_queues([QueueRow("x", rows[0].counts, None), rows[0]], "oldest")[0].name == "alpha"
    with pytest.raises(ValueError):
        sort_queues(rows, "bogus")
    assert truncate("abcdef", 4) == "abc…" and truncate("abc", 5) == "abc" and truncate("abc", 0) == ""
    text = render(collect(broker), sort="pending", width=20)
    assert max(len(line) for line in text.splitlines()) <= 20
    doc = json.loads(Dashboard(broker, as_json=True).render())
    assert [q["name"] for q in doc["queues"]] == ["alpha", "beta"] and doc["rates"] == {}


# ---------------------------------------------------------------- mutex

def test_mutex_basic_and_expiry():
    clock = ManualClock(100.0)
    m = MutexManager(clock, default_ttl=10)
    a = m.try_acquire("r", "a")
    assert a and m.try_acquire("r", "b") is None and m.locked("r")
    clock.advance(10)
    assert not m.locked("r")
    b = m.try_acquire("r", "b")
    assert b and m.release(a) is False
    with pytest.raises(MutexLost):
        m.renew(a)
    assert m.renew(b, ttl=50).expires_at == 160.0
    assert m.release(b) and m.held() == []
    st = m.stats()["r"]
    assert (st["acquired"], st["contended"], st["expired"], st["released"], st["renewed"]) == (2, 1, 1, 1, 1)


def test_mutex_hold_and_wait():
    m = MutexManager(ManualClock(0.0))
    with m.hold("r", "a") as lease:
        assert m.holder("r") == lease
        with pytest.raises(MutexBusy):
            with m.hold("r", "b"):
                pass
        got = []
        t = threading.Thread(target=lambda: got.append(m.acquire("r", "c", timeout=2.0)))
        t.start()
    t.join(3)
    assert got[0] is not None and got[0].owner == "c"


def test_mutex_job_integration(broker):
    m = MutexManager(broker.clock)
    seen = []

    @exclusive(m, lambda ctx: ctx.payload["acct"])
    def handler(ctx):
        seen.append(m.holder(ctx.payload["acct"]).owner)
        return "ok"

    class Ctx:
        def __init__(self, job_id, acct):
            self.job_id, self.payload, self.beats = job_id, {"acct": acct}, 0

        def heartbeat(self):
            self.beats += 1

    c1 = Ctx("job-1", "acme")
    assert handler(c1) == "ok" and seen == ["job-1"] and not m.locked("acme")
    with ctx_lock(m, Ctx("job-2", "x"), "acme") as held:
        with pytest.raises(Retry) as exc:
            handler(c1)
        assert exc.value.delay == 5.0
        held.heartbeat()
        assert held.ctx.beats == 1


# ---------------------------------------------------------------- chaos

def test_chaos_raises_and_removes_hooks(broker):
    chaos = Chaos(broker, seed=1)
    fault = chaos.fail("enqueue", limit=2)
    with chaos:
        assert broker.hooks.count("enqueue") == 1
        for _ in range(3):
            try:
                broker.enqueue("q", "k")
            except InjectedFault:
                pass
        assert fault.injected == 2 and fault.seen == 2
    assert broker.hooks.count() == 0
    broker.enqueue("q", "k")
    assert chaos.total_injected() == 2 and "2/2 injected" in chaos.render()


def test_chaos_probability_is_seeded(broker):
    def run(seed):
        c = Chaos(ManualBrokerHooks(broker), seed=seed)
        f = c.fail("reserve", probability=0.5)
        with c:
            for _ in range(40):
                try:
                    c._fire("reserve", {})
                except InjectedFault:
                    pass
        return f.injected

    assert run(4) == run(4) and 0 < run(4) < 40


class ManualBrokerHooks:
    def __init__(self, broker):
        self.hooks = broker.hooks


def test_chaos_delay_when_and_disable(broker):
    slept = []
    chaos = Chaos(broker, sleep=slept.append)
    chaos.delay("enqueue", 0.25, when=lambda kw: kw["job"].queue == "slow", name="d")
    with chaos:
        broker.enqueue("fast", "k")
        broker.enqueue("slow", "k")
        chaos.disable("d")
        broker.enqueue("slow", "k")
    assert slept == [0.25] and chaos.stats()["d"]["injected"] == 1
    with pytest.raises(ValueError):
        chaos.fail("nope")
    with pytest.raises(ValueError):
        chaos.fail("enqueue", probability=2)


def test_chaos_fault_abandons_operation(broker):
    chaos = Chaos(broker)
    chaos.fail("ack.before_commit", limit=1, exception=lambda: RuntimeError("drill"))
    broker.enqueue("q", "k")
    res = broker.reserve("w")
    with chaos:
        with pytest.raises(RuntimeError):
            broker.ack(res.token)
        broker.ack(res.token)
    assert broker.jobs()[0].state == "done"


# ---------------------------------------------------------------- healthcheck

def test_health_in_memory_thresholds(broker, clock):
    assert check(broker).status == OK and liveness(broker) and readiness(broker)
    for _ in range(3):
        broker.enqueue("q", "k")
    clock.advance(120)
    r = check(broker, Thresholds(max_backlog=(2, 10), max_oldest_pending=(60, 100), max_leases=(1, 2)))
    assert r.get("backlog").status == WARN and r.get("oldest").status == FAIL
    assert not r.ready and r.live and "oldest pending 120s" in r.render()
    broker.pause("q")
    assert check(broker, Thresholds(max_oldest_pending=(60, 100))).get("oldest").status == OK
    broker.resume("q")
    broker.reserve("w")
    broker.reserve("w")
    assert check(broker, Thresholds(max_leases=(1, 2))).get("leases").status == FAIL
    assert check(broker).to_dict()["checks"][0]["name"] == "broker"


def test_health_durable_checkpoint_and_wal(durable, clock):
    r = check(durable)
    assert r.get("wal").status == OK and r.get("checkpoint").status == WARN
    durable.enqueue("q", "k")
    durable.checkpoint()
    assert check(durable).get("checkpoint").status == OK
    clock.advance(2 * 86400)
    assert check(durable).get("checkpoint").status == FAIL
    os.rename(os.path.join(durable.data_dir, "wal"), os.path.join(durable.data_dir, "wal.moved"))
    assert check(durable).get("wal").status == FAIL


def test_health_runtime_and_closed(tmp_path):
    rt = Runtime(None)
    assert readiness(rt)
    rt.stop()
    r = check(rt)
    assert not r.live and not r.ready and len(r.results) == 1


# ---------------------------------------------------------------- batching

def test_batcher_flushes_on_size(broker):
    b = EnqueueBatcher(broker, max_size=3, max_age=100)
    tickets = [b.add("q", "k", {"i": i}) for i in range(2)]
    assert len(b) == 2 and broker.stats()["jobs"] == 0 and not tickets[0].flushed
    tickets.append(b.add("q", "k", {"i": 2}, priority=1))
    assert broker.stats()["jobs"] == 3 and all(t.flushed and t.result.ok for t in tickets)
    assert broker.get(tickets[2].result.job_id).priority == 1
    assert b.stats()["by_size"] == 1 and b.stats()["largest"] == 3


def test_batcher_flushes_on_age(broker, clock):
    b = EnqueueBatcher(broker, max_size=100, max_age=5)
    t = b.add("q", "k")
    clock.advance(4)
    assert b.poll() == 0 and b.age() == 4
    clock.advance(1)
    assert b.poll() == 1 and t.result.job_id and b.age() is None and b.stats()["by_age"] == 1


def test_batcher_errors_and_close(broker):
    b = EnqueueBatcher(broker, max_size=10)
    bad = b.add("BAD QUEUE", "k")
    good = b.add("q", "k")
    assert b.close() == 2
    assert not bad.result.ok and good.result.ok and b.stats()["errors"] == 1
    with pytest.raises(RuntimeError):
        b.add("q", "k")


def test_batcher_threads_no_duplicates(broker):
    b = EnqueueBatcher(broker, max_size=7, max_age=100)

    def produce(n):
        for i in range(25):
            b.add("q", "k", {"n": n, "i": i})

    threads = [threading.Thread(target=produce, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    b.flush()
    assert broker.stats()["jobs"] == 100 and b.stats()["items"] == 100
