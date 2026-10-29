"""Existing behaviour that must keep working."""

import io
import json
import os
import subprocess
import sys

import pytest

from hiddenkit import T0, make
from taskmill import (BrokerConfig, InvalidTransition, LeaseLost, Registry, Retry, Schedule, Scheduler,
                      UnknownJob, ValidationError, parse_backoff, run_one)
from taskmill import bulk, deadletter, export
from taskmill.admin import AdminApp
from taskmill.client import AdminClient, AdminError
from taskmill.config import QueueConfig
from taskmill.errors import ConfigError


def cli(*args):
    p = subprocess.run([sys.executable, "-m", "taskmill", *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


# ------------------------------------------------------------------ broker

def test_basic_lifecycle_and_errors():
    b, clock = make()
    a = b.enqueue("q", "k", {"x": [1, 2]}, tags=["t", "t", "u"]).job_id
    assert b.get(a).tags == ["t", "u"]
    r = b.reserve(worker="w")
    assert b.leases()[0]["worker"] == "w"
    b.ack(r.token, [1, (2, 3)])
    assert b.result(a).result == [1, [2, 3]]
    with pytest.raises(LeaseLost, match="released"):
        b.nack(r.token, "x")
    with pytest.raises(UnknownJob):
        b.cancel("job-404")


def test_ack_expired_token_message():
    b, clock = make()
    b.enqueue("q", "k")
    r = b.reserve()
    clock.advance(30)
    with pytest.raises(LeaseLost, match="expired"):
        b.ack(r.token)
    b.reap()
    with pytest.raises(LeaseLost, match="expired"):
        b.ack(r.token)


def test_superseded_message():
    b, clock = make()
    b.enqueue("q", "k")
    r = b.reserve()
    clock.advance(30)
    b.reserve()
    with pytest.raises(LeaseLost):
        b.ack(r.token)


def test_backoff_per_queue_and_per_job():
    cfg = dict(queues={"slow": QueueConfig(backoff={"kind": "fixed", "delay": 60})})
    b, clock = make(**cfg)
    b.enqueue("slow", "k")
    b.enqueue("fast", "k", backoff={"kind": "linear", "base": 3, "step": 1})
    b.enqueue("dflt", "k")
    for q, want in (("slow", 60), ("fast", 3), ("dflt", 1)):
        r = b.reserve(queues=[q])
        b.nack(r.token, "e")
        assert b.get(r.job_id).run_at == clock() + want


def test_exponential_backoff_sequence_through_broker():
    b, clock = make(backoff={"kind": "exponential", "base": 2, "factor": 2, "max": 10}, max_attempts=6)
    jid = b.enqueue("q", "k").job_id
    delays = []
    for _ in range(5):
        r = b.reserve()
        b.nack(r.token, "e")
        j = b.get(jid)
        delays.append(j.run_at - clock())
        clock.advance(j.run_at - clock())
    assert delays == [2, 4, 8, 10, 10]
    r = b.reserve()
    assert b.nack(r.token, "e") == "failed"
    assert len(b.get(jid).errors) == 5   # max_errors_kept


def test_jittered_backoff_deterministic_per_job():
    spec = {"kind": "exponential", "base": 10, "factor": 2, "jitter": "full"}
    b1, c1 = make(backoff=spec)
    b2, c2 = make(backoff=spec)
    for b in (b1, b2):
        b.enqueue("q", "k")
        r = b.reserve()
        b.nack(r.token, "e")
    assert b1.get("job-1").run_at == b2.get("job-1").run_at
    assert T0 <= b1.get("job-1").run_at <= T0 + 10


def test_max_attempts_per_queue():
    b, clock = make(queues={"once": QueueConfig(max_attempts=1)})
    b.enqueue("once", "k")
    r = b.reserve()
    assert r.max_attempts == 1
    assert b.nack(r.token, "e") == "failed"


def test_visibility_timeout_per_queue():
    b, clock = make(queues={"long": QueueConfig(visibility_timeout=300)})
    b.enqueue("long", "k")
    r = b.reserve()
    assert r.deadline == clock() + 300
    assert b.heartbeat(r.token) == clock() + 300


def test_heartbeat_validation_and_extend():
    b, clock = make()
    b.enqueue("q", "k")
    r = b.reserve()
    with pytest.raises(ValidationError):
        b.heartbeat(r.token, extend=0)
    assert b.heartbeat(r.token, extend=100) == clock() + 100
    assert b.heartbeat(r.token, extend=5) == clock() + 100   # never shortens


def test_cancel_and_retry_cycle_keeps_key():
    b, clock = make()
    a = b.enqueue("q", "k", idempotency_key="K").job_id
    b.cancel(a)
    assert b.enqueue("q", "k", idempotency_key="K").job_id == a
    b.retry(a)
    assert b.get(a).state == "pending"
    assert b.enqueue("q", "k", idempotency_key="K").job_id == a
    b.cancel(a)
    with pytest.raises(InvalidTransition):
        b.set_priority(a, 3)


def test_purge_frees_key():
    b, clock = make(retention=10, dedup_window=1000)
    a = b.enqueue("q", "k", idempotency_key="K").job_id
    b.cancel(a)
    clock.advance(10)
    assert b.purge() == [a]
    assert b.enqueue("q", "k", idempotency_key="K").created


def test_rate_limit_and_pause_stats():
    b, clock = make(queues={"rl": QueueConfig(rate=2, burst=1, paused=True)})
    b.enqueue("rl", "k")
    b.enqueue("rl", "k")
    st = b.queue_stats("rl")
    assert st["paused"] and st["rate_limited"] and st["pending"] == 2
    assert b.reserve() is None
    b.resume("rl")
    assert b.reserve() is not None and b.reserve() is None
    clock.advance(0.5)
    assert b.reserve() is not None


def test_payload_limits():
    b, _ = make(max_payload_bytes=100)
    with pytest.raises(ValidationError):
        b.enqueue("q", "k", "x" * 200)
    b2, _ = make(max_result_bytes=64)
    b2.enqueue("q", "k")
    r = b2.reserve()
    from taskmill.errors import ResultTooLarge
    with pytest.raises(ResultTooLarge):
        b2.ack(r.token, "y" * 100)
    b2.ack(r.token, "ok")


def test_wait_on_failure():
    b, clock = make()
    b.enqueue("q", "k", max_attempts=1)
    r = b.reserve()
    b.nack(r.token, "nope")
    v = b.wait(r.job_id, timeout=1)
    assert v.state == "failed" and v.error == "nope" and not v.ok


def test_config_roundtrip_and_errors(tmp_path):
    cfg = BrokerConfig(visibility_timeout=12, queues={"a": QueueConfig(rate=3)})
    again = BrokerConfig.from_dict(cfg.to_dict())
    assert again.visibility_timeout == 12 and again.queues["a"].rate == 3
    with pytest.raises(ConfigError):
        BrokerConfig.from_dict({"visibilty_timeout": 3})
    with pytest.raises(ConfigError):
        BrokerConfig(wal_fsync="sometimes").validate()
    env = BrokerConfig.from_env({"TASKMILL_MAX_ATTEMPTS": "9"})
    assert env.max_attempts == 9


# ------------------------------------------------------------ worker pool

def test_worker_pool_end_to_end_with_retries():
    from taskmill import Broker, WorkerPool, default_registry
    b = Broker(None, BrokerConfig(backoff={"kind": "fixed", "delay": 0}, visibility_timeout=10))
    ids = [b.enqueue("q", "fail", {"until_attempt": 2}).job_id for _ in range(5)]
    ids += [b.enqueue("q", "echo", i).job_id for i in range(5)]
    with WorkerPool(b, default_registry(), concurrency=4, poll=0.01) as pool:
        assert pool.drain(timeout=20)
    assert all(b.result(i).ok for i in ids)
    assert b.metrics.value("worker.handled", kind="fail", outcome="retry") == 5
    assert b.metrics.value("jobs.retried", queue="q") == 5


def test_run_one_handler_outcomes():
    b, clock = make()
    reg = Registry()

    def h(ctx):
        if ctx.payload == "retry":
            raise Retry(delay=7)
        raise ValueError("bad")

    reg.register("h", h)
    a = b.enqueue("q", "h", "retry").job_id
    c = b.enqueue("q", "h", "boom").job_id
    run_one(b, reg)
    run_one(b, reg)
    assert b.get(a).run_at == clock() + 7
    assert b.get(c).last_error == "ValueError: bad"
    assert run_one(b, reg) is None


# --------------------------------------------------------------- scheduler

def test_scheduler_cron_catchup():
    b, _ = make()
    s = Scheduler(b, [Schedule("q5", "q", "echo", cron="*/5 * * * *", max_catchup=3)], start_at=0)
    fired = s.tick(now=3600)
    assert [f.slot for f in fired] == [3000, 3300, 3600]
    assert b.metrics.value("scheduler.skipped", schedule="q5") == 9
    assert s.tick(now=3600) == []


# -------------------------------------------------------- admin / client

def test_admin_client_flow():
    b, clock = make()
    c = AdminClient.local(AdminApp(b))
    j = c.enqueue("q", "echo", {"a": 1}, idempotency_key="X-1")
    assert c.enqueue("q", "echo", {"a": 2}, idempotency_key="X-1") == j
    assert c.job(j)["state"] == "pending"
    c.pause("q")
    assert c.queue("q")["paused"] is True
    c.resume("q")
    r = b.reserve()
    assert c.leases()[0]["token"].endswith("...")
    assert c.job(j)["lease_token"].endswith("...")
    clock.advance(31)
    assert c.reap() == [j]
    assert c.metrics()["jobs.expired{queue=q}"] == 1
    with pytest.raises(AdminError) as ei:
        c.set_priority(j, 42)
    assert ei.value.status == 400
    with pytest.raises(AdminError) as ei:
        c.retry(j)
    assert ei.value.status == 409
    assert c.health() == {"ok": True, "closed": False}


def test_admin_trace(tmp_path):
    from taskmill.tracing import Tracer
    b, clock = make()
    tr = Tracer(b).install()
    app = AdminApp(b, tr)
    j = b.enqueue("q", "echo").job_id
    r = b.reserve(worker="w1")
    b.heartbeat(r.token)
    st, doc = app("GET", f"/trace?job_id={j}")
    assert st == 200 and [e["point"] for e in doc["events"]] == ["enqueue", "reserve", "heartbeat"]
    assert all(len(e.get("token") or "") <= 6 for e in doc["events"])
    assert AdminApp(b)("GET", "/trace")[0] == 404


# ------------------------------------------------------------------ tools

def test_bulk_and_deadletter():
    b, clock = make()
    res = bulk.enqueue_many(b, [{"queue": "q", "kind": "k", "payload": 1},
                                {"queue": "Q!", "kind": "k"},
                                {"queue": "q", "kind": "k", "idempotency_key": "d"},
                                {"queue": "q", "kind": "k", "idempotency_key": "d"}])
    assert [r.ok for r in res] == [True, False, True, True] and res[3].created is False
    for _ in range(2):
        r = b.reserve()
        b.nack(r.token, f"ConnectionError: host 10.0.0.{r.job_id[-1]} unreachable", permanent=True)
    groups = deadletter.group_by_error(b)
    assert list(groups.values()) == [["job-1", "job-2"]]
    out = io.StringIO()
    assert deadletter.export_jsonl(b, out) == 2
    rep = deadletter.requeue_signature(b, next(iter(groups)))
    assert rep["requeued"] == ["job-1", "job-2"]


def test_export_import_roundtrip():
    b, clock = make()
    b.enqueue("q", "k", 1, idempotency_key="A")
    b.enqueue("q", "k", 2, delay=50, priority=2)
    r = b.reserve()
    out = io.StringIO()
    export.export_jobs(b, out)
    b2, _ = make(clock=clock)
    mapping = export.import_jobs(b2, out.getvalue().splitlines())
    assert len(mapping) == 2
    assert {j.state for j in b2.jobs()} == {"pending", "delayed"}
    assert b2.enqueue("q", "k", idempotency_key="A").created is False


# ---------------------------------------------------------------------- cli

def test_cli_full(tmp_path):
    d = str(tmp_path / "data")
    assert cli("enqueue", d, "q", "sum", "--payload", '{"values": [1, 2, 3]}', "--key", "Order 12")[1] == "job-1 created\n"
    assert cli("enqueue", d, "q", "sum", "--payload", '{"values": [9]}', "--key", "Order 12")[1] == "job-1 existing\n"
    rc, out, _ = cli("run", d, "--until-idle", "--timeout", "30")
    assert rc == 0 and out.strip() == "pending=0 delayed=0 reserved=0 done=1 failed=0 cancelled=0"
    rc, out, _ = cli("stats", d, "--json")
    doc = json.loads(out)
    assert doc["queues"]["q"]["done"] == 1
    rc, out, _ = cli("wal", "verify", d)
    assert rc == 0 and json.loads(out)["ok"]
    rc, out, _ = cli("recover", d)
    assert rc == 0 and out.startswith("recovered 1 job(s)")
    rc, out, err = cli("enqueue", d, "Bad Queue", "k")
    assert rc == 1 and err.startswith("taskmill: ")
