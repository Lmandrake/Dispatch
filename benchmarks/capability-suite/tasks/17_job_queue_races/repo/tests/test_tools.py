import io
import json
import subprocess
import sys

import pytest

from taskmill import Broker, BrokerConfig, ManualClock, Registry, ValidationError, WorkerPool, run_one
from taskmill import bulk, deadletter, export, inspect as insp, report
from taskmill.notify import Outbox
from taskmill.tracing import Tracer, format_event
from taskmill.workflow import Workflow, WorkflowRunner


def finish_all(broker, reg):
    while run_one(broker, reg) is not None:
        pass


def test_workflow_diamond(broker):
    reg = Registry()
    reg.register("step", lambda ctx: ctx.payload)
    wf = Workflow("nightly")
    e = wf.step("extract", "q", "step", "e")
    a = wf.step("load-a", "q", "step", "a", after=[e])
    b = wf.step("load-b", "q", "step", "b", after=[e])
    wf.step("report", "q", "step", "r", after=[a, b])
    runner = WorkflowRunner(broker)
    rid = runner.start(wf)
    assert runner.run(rid).steps == {"extract": "enqueued", "load-a": "waiting", "load-b": "waiting",
                                     "report": "waiting"}
    finish_all(broker, reg)
    assert runner.advance(rid) == ["load-a", "load-b"]
    assert runner.advance(rid) == []
    finish_all(broker, reg)
    assert runner.advance(rid) == ["report"]
    finish_all(broker, reg)
    runner.advance(rid)
    assert runner.run(rid).state == "done"


def test_workflow_failure_skips_dependents(broker):
    reg = Registry()
    reg.register("ok", lambda ctx: 1)
    reg.register("bad", lambda ctx: (_ for _ in ()).throw(__import__("taskmill").PermanentError("no")))
    wf = Workflow("w")
    x = wf.step("x", "q", "bad")
    wf.step("y", "q", "ok", after=[x])
    runner = WorkflowRunner(broker)
    rid = runner.start(wf)
    finish_all(broker, reg)
    runner.advance(rid)
    run = runner.run(rid)
    assert run.steps == {"x": "failed", "y": "skipped"} and run.state == "failed"


def test_workflow_validation():
    wf = Workflow("w")
    with pytest.raises(ValidationError):
        wf.step("a", "q", "k", after=["nope"])
    wf.step("a", "q", "k")
    with pytest.raises(ValidationError):
        wf.step("a", "q", "k")
    with pytest.raises(ValidationError):
        Workflow("a/b")


def test_workflow_attach_to_pool():
    b = Broker(None, BrokerConfig(visibility_timeout=10))
    reg = Registry()
    reg.register("s", lambda ctx: ctx.payload)
    wf = Workflow("chain")
    prev = None
    for i in range(4):
        prev = wf.step(f"s{i}", "q", "s", i, after=[prev] if prev else None)
    runner = WorkflowRunner(b)
    with WorkerPool(b, reg, concurrency=2, poll=0.01) as pool:
        runner.attach(pool)
        rid = runner.start(wf)
        for _ in range(500):
            if runner.run(rid).state == "done":
                break
            import time
            time.sleep(0.01)
        runner.detach()
    assert runner.run(rid).state == "done"


def test_outbox_delivers_and_retries(broker):
    reg = Registry()
    reg.register("e", lambda ctx: 1)
    box = Outbox(broker, max_tries=2)
    got, flaky = [], {"n": 0}
    box.subscribe("all", got.append)

    def bad(note):
        flaky["n"] += 1
        raise RuntimeError("down")

    box.subscribe("flaky", bad, queues=["q"])
    broker.enqueue("q", "e")
    broker.enqueue("other", "e")
    finish_all(broker, reg)
    assert box.poll() == 2
    assert box.flush() == {"all": 2, "flaky": 0}
    assert [n.job_id for n in got] == ["job-1", "job-2"]
    assert box.backlog() == {"all": 0, "flaky": 1}
    box.flush()
    assert box.counts()["flaky"] == {"delivered": 0, "dropped": 1, "pending": 0}
    assert box.poll() == 0


def test_tracer_and_format(broker):
    tr = Tracer(broker).install()
    broker.enqueue("q", "k")
    r = broker.reserve(worker="w1")
    evs = tr.events(job_id=r.job_id)
    assert [e["point"] for e in evs] == ["enqueue", "reserve"]
    line = format_event(evs[1])
    assert line.startswith("#2 ") and "worker=w1" in line and r.token not in line
    tr.uninstall()
    broker.enqueue("q", "k")
    assert len(tr) == 2


def test_report_tables(broker):
    broker.enqueue("q", "k")
    broker.enqueue("z", "k")
    broker.reserve(queues=["z"])
    t = report.queue_table(broker)
    lines = t.splitlines()
    assert lines[0].split() == ["queue", "pending", "delayed", "reserved", "done", "failed", "cancelled"]
    assert lines[-1].split() == ["total", "1", "0", "1", "0", "0", "0"]
    assert "job-2" in report.lease_table(broker)
    assert [l.split() for l in report.metrics_table({"a": 1.0, "b": 0.25}).splitlines()[2:]] == [["a", "1"], ["b", "0.25"]]


def test_inspect_describe_and_history(tmp_path, clock):
    d = str(tmp_path / "d")
    b = Broker(d, BrokerConfig(visibility_timeout=30), clock=clock)
    b.enqueue("q", "k")
    r = b.reserve(worker="w1")
    b.nack(r.token, "boom")
    b.checkpoint()
    b.enqueue("q", "k")
    b.close()
    doc = insp.describe(d)
    assert doc["error"] is None and doc["snapshots"][0]["last_seq"] == 3
    assert doc["ops"] == {"enqueue": 1}  # older segments were dropped by the checkpoint
    assert doc["replay_records"] == 1
    hist = insp.job_history(d, "job-2")
    assert [h["op"] for h in hist] == ["enqueue"]


def test_inspect_cli(tmp_path, clock):
    d = str(tmp_path / "d")
    b = Broker(d, BrokerConfig(visibility_timeout=30), clock=clock)
    b.enqueue("q", "k")
    r = b.reserve(worker="w7")
    b.ack(r.token, 1)
    b.close()
    p = subprocess.run([sys.executable, "-m", "taskmill", "inspect", d, "--job", "job-1"], capture_output=True,
                       text=True, timeout=60)
    rows = p.stdout.splitlines()
    assert [r.split()[1] for r in rows] == ["enqueue", "reserve", "ack"]
    assert "worker=w7" in rows[1]


def test_bulk_select_and_cancel(broker):
    for i in range(4):
        broker.enqueue("q", "a" if i % 2 else "b", i, tags=["x"] if i < 2 else None)
    assert bulk.select(broker, kind="a") == ["job-2", "job-4"]
    rep = bulk.cancel_where(broker, tag="x")
    assert rep == {"cancelled": ["job-1", "job-2"], "skipped": []}
    assert bulk.retry_where(broker, state="cancelled")["retried"] == ["job-1", "job-2"]


def test_deadletter_signature():
    assert deadletter.error_signature("timeout after 30s on 10.1.2.3") == "timeout after #s on #.#.#.#"
    assert deadletter.error_signature("id deadbeefcafe failed") == "id <hex> failed"
    assert deadletter.error_signature(None) == "(no error recorded)"


def test_export_skips_finished(broker):
    broker.enqueue("q", "k", 1)
    r = broker.reserve()
    broker.ack(r.token)
    broker.enqueue("q", "k", 2)
    out = io.StringIO()
    assert export.export_jobs(broker, out) == 2
    other = Broker(None, clock=ManualClock(5))
    assert list(export.import_jobs(other, out.getvalue().splitlines()).keys()) == ["job-2"]
