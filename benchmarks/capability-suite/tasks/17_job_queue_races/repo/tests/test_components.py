import io
import json
import subprocess
import sys
import threading

import pytest

from taskmill import (Broker, BrokerConfig, ManualClock, Metrics, Registry, Schedule, Scheduler,
                      WorkerPool, default_registry, parse_backoff, run_one)
from taskmill.admin import AdminApp
from taskmill.client import AdminClient
from taskmill.cron import parse_cron
from taskmill.errors import ConfigError, CronError, InvalidKey, PermanentError, Retry
from taskmill.idempotency import normalize_key


# ------------------------------------------------------------------ backoff

def test_backoff_exponential():
    b = parse_backoff({"kind": "exponential", "base": 1, "factor": 2, "max": 10})
    assert b.schedule(6) == [1, 2, 4, 8, 10, 10]


def test_backoff_linear_fixed():
    assert parse_backoff({"kind": "linear", "base": 2, "step": 3}).schedule(3) == [2, 5, 8]
    assert parse_backoff({"kind": "fixed", "delay": 7}).schedule(2) == [7, 7]


def test_backoff_jitter_deterministic():
    b = parse_backoff({"kind": "fixed", "delay": 10, "jitter": "full"})
    assert b.delay(1, "job-1") == b.delay(1, "job-1")
    assert 0 <= b.delay(1, "job-1") <= 10
    e = parse_backoff({"kind": "fixed", "delay": 10, "jitter": "equal"})
    assert 5 <= e.delay(3, "job-9") <= 10


def test_backoff_rejects_bad_specs():
    with pytest.raises(ConfigError):
        parse_backoff({"kind": "weird"})
    with pytest.raises(ConfigError):
        parse_backoff({"kind": "fixed", "delay": 1, "factor": 2})
    with pytest.raises(ConfigError):
        parse_backoff({"kind": "exponential", "base": 1, "factor": 0.5})


# ------------------------------------------------------------- idempotency

def test_normalize_key_basics():
    assert normalize_key("order-17") == normalize_key("order-17")
    with pytest.raises(InvalidKey):
        normalize_key("   ")
    with pytest.raises(InvalidKey):
        normalize_key("a\nb")
    with pytest.raises(InvalidKey):
        normalize_key("x" * 201)


# ----------------------------------------------------------------- metrics

def test_metrics_labels_and_snapshot():
    m = Metrics(clock=ManualClock(5))
    m.inc("jobs.acked", queue="a")
    m.inc("jobs.acked", 2, queue="b")
    m.inc("checkpoints")
    m.observe("worker.run_seconds", 0.02)
    snap = m.snapshot()
    assert snap["jobs.acked{queue=a}"] == 1 and snap["jobs.acked{queue=b}"] == 2
    assert snap["checkpoints"] == 1
    assert snap["worker.run_seconds.count"] == 1 and snap["worker.run_seconds.le_0.05"] == 1
    assert m.value("jobs.acked", queue="b") == 2
    assert m.counter("jobs.acked").total() == 3
    assert "checkpoints 1\n" in m.render_text()


def test_metrics_type_conflict():
    m = Metrics()
    m.inc("x")
    with pytest.raises(ValueError):
        m.gauge("x")


# -------------------------------------------------------------------- cron

def test_cron_parse_and_next():
    e = parse_cron("*/15 9-17 * * mon-fri")
    t = e.next_after(0)  # 1970-01-01 was a Thursday
    assert t == 9 * 3600
    assert e.next_after(t) == 9 * 3600 + 900
    assert parse_cron("@daily").next_after(10) == 86400


def test_cron_errors():
    for bad in ["", "* * *", "61 * * * *", "5-1 * * * *", "*/0 * * * *"]:
        with pytest.raises(CronError):
            parse_cron(bad)


# --------------------------------------------------------------- scheduler

def test_scheduler_fires_interval(clock):
    b = Broker(None, clock=clock)
    s = Scheduler(b, [Schedule("tick", "q", "echo", {"x": 1}, every=60)], start_at=0)
    fired = s.tick(now=120)
    assert [f.slot for f in fired] == [120]  # max_catchup=1
    assert b.metrics.value("scheduler.skipped", schedule="tick") == 1
    again = Scheduler(b, [Schedule("tick", "q", "echo", {"x": 1}, every=60)], start_at=60)
    assert [f.created for f in again.tick(now=120)] == [False]


def test_schedule_validation():
    from taskmill import ValidationError
    with pytest.raises(ValidationError):
        Schedule("bad name", "q", "k", every=1)
    with pytest.raises(ValidationError):
        Schedule("n", "q", "k")


# ----------------------------------------------------------------- workers

def test_worker_pool_runs_jobs():
    b = Broker(None, BrokerConfig(visibility_timeout=5))
    reg = default_registry()
    ids = [b.enqueue("q", "sum", {"values": [i, i]}).job_id for i in range(10)]
    with WorkerPool(b, reg, concurrency=3, poll=0.01) as pool:
        assert pool.drain(timeout=10)
    assert [b.result(i).result for i in ids] == [2 * i for i in range(10)]
    assert b.metrics.value("worker.handled", kind="sum", outcome="ok") == 10


def test_worker_retry_and_permanent():
    b = Broker(None, BrokerConfig(backoff={"kind": "fixed", "delay": 0}))
    ok = b.enqueue("q", "fail", {"until_attempt": 3}).job_id
    bad = b.enqueue("q", "fail", {"permanent": True}).job_id
    nohandler = b.enqueue("q", "mystery").job_id
    with WorkerPool(b, default_registry(), concurrency=2, poll=0.01) as pool:
        assert pool.drain(timeout=10)
    assert b.result(ok).result == {"succeeded_on": 3}
    assert b.result(bad).state == "failed"
    assert b.result(nohandler).state == "failed"


def test_run_one_inline(broker):
    reg = Registry()
    reg.register("double", lambda ctx: ctx.payload * 2)
    a = broker.enqueue("q", "double", 21).job_id
    assert run_one(broker, reg) == a
    assert broker.result(a).result == 42


def test_handler_retry_exception(broker, clock):
    reg = Registry()

    def h(ctx):
        raise Retry(delay=99, reason="not yet")

    reg.register("x", h)
    a = broker.enqueue("q", "x").job_id
    run_one(broker, reg)
    j = broker.get(a)
    assert j.state == "delayed" and j.run_at == clock() + 99 and j.last_error == "not yet"


# ------------------------------------------------------------------- admin

def test_admin_roundtrip(broker):
    app = AdminApp(broker)
    c = AdminClient.local(app)
    job_id = c.enqueue("q", "echo", {"a": 1}, priority=2)
    assert c.job(job_id)["priority"] == 2
    assert c.queues()[0]["pending"] == 1
    assert c.order("q") == [job_id]
    assert app("GET", "/nope")[0] == 404
    assert app("DELETE", "/stats")[0] == 405
    assert app("GET", "/jobs/job-999")[0] == 404
    status, doc = app("POST", "/queues/q/jobs", {"kind": "echo", "idempotency_key": "k-1"})
    assert status == 201
    status, doc2 = app("POST", "/queues/q/jobs", {"kind": "echo", "idempotency_key": "k-1"})
    assert status == 200 and doc2["job_id"] == doc["job_id"]
    assert c.cancel(job_id) is True


# --------------------------------------------------------------------- cli

def run_cli(*args):
    p = subprocess.run([sys.executable, "-m", "taskmill", *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def test_cli_enqueue_list_run(tmp_path):
    d = str(tmp_path / "data")
    rc, out, _ = run_cli("enqueue", d, "q", "echo", "--payload", '{"a": 1}')
    assert rc == 0 and out.strip() == "job-1 created"
    rc, out, _ = run_cli("list", d)
    assert "job-1" in out and "1 job(s)" in out
    rc, out, _ = run_cli("run", d, "--until-idle", "--timeout", "20")
    assert rc == 0 and "done=1" in out
    rc, out, _ = run_cli("show", d, "job-1")
    assert json.loads(out)["result"] == {"a": 1}


def test_cli_backoff_and_cron():
    rc, out, _ = run_cli("backoff", '{"kind": "exponential", "base": 1, "factor": 2, "max": 4}', "--attempts", "4")
    assert rc == 0 and out.splitlines() == ["exponential 1s x2, max 4s", "attempt 1: 1.000s",
                                            "attempt 2: 2.000s", "attempt 3: 4.000s", "attempt 4: 4.000s"]
    rc, out, _ = run_cli("cron", "@hourly", "--count", "2")
    assert out.splitlines() == ["1970-01-01T01:00  3600", "1970-01-01T02:00  7200"]


def test_cli_error_exit(tmp_path):
    rc, _, err = run_cli("show", str(tmp_path / "d"), "job-5")
    assert rc == 1 and "no job job-5" in err
