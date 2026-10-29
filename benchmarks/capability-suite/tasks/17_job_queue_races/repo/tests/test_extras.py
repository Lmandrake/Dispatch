import gzip
import json
import os

import pytest

from taskmill import Broker, BrokerConfig, ManualClock
from taskmill.archive import Archive, archive_then_purge, day_of
from taskmill.audit import AuditedBroker, AuditLog
from taskmill.migrate import check_row, migrate, to_job_dict
from taskmill.notify import Outbox
from taskmill.schema import SchemaError, SchemaRegistry, check_schema, validate, validated_enqueue
from taskmill.sim import Arrival, make_arrivals, percentile, simulate
from taskmill.top import Dashboard, format_duration
from taskmill.webhooks import WebhookDispatcher, sign, verify_signature


def finish(broker, queue="q", kind="k", ok=True):
    jid = broker.enqueue(queue, kind, {"x": 1}).job_id
    res = broker.reserve("w")
    if ok:
        broker.ack(res.token, {"done": True})
    else:
        broker.nack(res.token, "boom", permanent=True)
    return jid


# ---------------------------------------------------------------- schema

ORDER = {
    "type": "object", "required": ["id", "items"], "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^ord-[0-9]+$"},
        "note": {"type": ["string", "null"], "maxLength": 5},
        "status": {"enum": ["new", "paid"]},
        "items": {"type": "array", "minItems": 1,
                  "items": {"type": "object", "required": ["qty"],
                            "properties": {"qty": {"type": "integer", "minimum": 1, "maximum": 10}}}},
    },
}


def test_schema_valid_payload():
    assert validate({"id": "ord-1", "items": [{"qty": 3}], "note": None, "status": "new"}, ORDER) == []


def test_schema_error_paths():
    bad = {"id": "x", "items": [{"qty": 2}, {"qty": 11}, {"qty": True}], "extra": 1, "note": "toolong"}
    got = {str(i) for i in validate(bad, ORDER)}
    assert "/id: does not match pattern '^ord-[0-9]+$'" in got
    assert "/items/1/qty: must be <= 10" in got
    assert "/items/2/qty: expected integer, got boolean" in got
    assert "/extra: is not allowed" in got
    assert "/note: longer than 5 character(s)" in got


def test_schema_required_and_enum():
    got = [str(i) for i in validate({"status": "gone"}, ORDER)]
    assert "/id: is required" in got and "/items: is required" in got
    assert any(g.startswith("/status: must be one of") for g in got)


def test_check_schema_rejects_malformed():
    with pytest.raises(Exception):
        check_schema({"type": "blob"})
    with pytest.raises(Exception):
        check_schema({"properties": {"a": {"pattern": "("}}})
    with pytest.raises(Exception):
        check_schema({"nope": 1})


def test_validated_enqueue(broker):
    reg = SchemaRegistry()
    reg.register("order", ORDER)
    jid = validated_enqueue(broker, reg, "q", "order", {"id": "ord-9", "items": [{"qty": 1}]}, priority=2)
    assert broker.get(jid.job_id).priority == 2
    with pytest.raises(SchemaError) as exc:
        validated_enqueue(broker, reg, "q", "order", {"id": "bad"})
    assert len(exc.value.issues) == 2
    assert broker.stats()["jobs"] == 1
    validated_enqueue(broker, reg, "q", "other", {"anything": True})


def test_registry_queue_override_and_strict(broker):
    reg = SchemaRegistry(strict=True)
    reg.register("k", {"type": "integer"})
    reg.register("k", {"type": "string"}, queue="special")
    assert reg.validate("a", "k", 3) == [] and reg.validate("special", "k", "s") == []
    assert reg.validate("special", "k", 3)
    assert reg.validate("a", "unknown", 1)[0].path == "/"
    assert reg.kinds() == ["k"] and reg.unregister("k")


# ---------------------------------------------------------------- archive

def test_archive_roundtrip_and_search(broker, clock, tmp_path):
    a, b = finish(broker, kind="one"), finish(broker, kind="two", ok=False)
    arc = Archive(str(tmp_path / "arc"))
    report = arc.add(broker.jobs(state="done") + broker.jobs(state="failed"))
    assert report.written == 2 and arc.days() == [day_of(clock())]
    assert arc.add(broker.jobs(state="done")).skipped == 1
    assert arc.get(a)["kind"] == "one" and arc.restore(b).state == "failed"
    assert [r["id"] for r in arc.search(kind="two")] == [b] and arc.count() == 2
    name = os.path.join(arc.directory, f"archive-{day_of(clock())}.jsonl.gz")
    with gzip.open(name, "rt") as fh:
        assert len(fh.read().splitlines()) == 2


def test_archive_rejects_unfinished(broker, tmp_path):
    broker.enqueue("q", "k")
    with pytest.raises(ValueError):
        Archive(str(tmp_path)).add(broker.jobs())


def test_archive_then_purge(clock, tmp_path):
    broker = Broker(None, BrokerConfig(retention=100), clock=clock)
    old = finish(broker)
    clock.advance(86400)
    new = finish(broker)
    clock.advance(50)
    report = archive_then_purge(broker, str(tmp_path / "arc"))
    assert report.purged == [old] and report.days == [day_of(clock() - 86450)]
    assert [j.id for j in broker.jobs()] == [new]
    assert Archive(str(tmp_path / "arc")).get(old) is not None
    assert Archive(str(tmp_path / "arc")).get(new) is None
    broker.close()


# ---------------------------------------------------------------- audit

def test_audit_records_before_delegating(broker, tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    ab = AuditedBroker(broker, log, actor="alice")
    jid = broker.enqueue("q", "k").job_id
    ab.set_priority(jid, 1)
    ab.pause("q")
    ab.resume("q")
    assert ab.cancel(jid) is True
    ab.retry(jid)
    ab.purge()
    ab.as_actor("bob").checkpoint()
    assert broker.get(jid).priority == 1 and broker.get(jid).state == "pending"
    assert [e.action for e in log.read(actor="alice")] == [
        "set_priority", "pause", "resume", "cancel", "retry", "purge", "purge.result"]
    assert log.read(actor="bob")[0].action == "checkpoint"
    assert log.read(target=jid, action="set_priority")[0].details == {"priority": 1}
    assert ab.stats()["jobs"] == 1


def test_audit_failure_and_canonical_lines(broker, tmp_path):
    path = str(tmp_path / "sub" / "audit.jsonl")
    log = AuditLog(path)
    ab = AuditedBroker(broker, log)
    with pytest.raises(Exception):
        ab.retry("job-nope")
    entries = list(log.entries())
    assert [e.action for e in entries] == ["retry", "retry.failed"]
    assert "error" in entries[1].details
    line = open(path).readline()
    assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")) + "\n"
    assert log.summary() == {"retry": 1, "retry.failed": 1} and len(log.tail(1)) == 1


def test_audit_time_filter(broker, clock, tmp_path):
    log = AuditLog(str(tmp_path / "a.jsonl"))
    ab = AuditedBroker(broker, log)
    ab.pause("q")
    clock.advance(10)
    ab.resume("q")
    assert [e.action for e in log.read(since=clock() - 5)] == ["resume"]
    assert [e.action for e in log.read(until=clock() - 5)] == ["pause"]


# ---------------------------------------------------------------- webhooks

class FakeTransport:
    def __init__(self, statuses):
        self.statuses = {url: list(s) for url, s in statuses.items()}
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers))
        s = self.statuses[url]
        v = s.pop(0) if len(s) > 1 else s[0]
        if isinstance(v, Exception):
            raise v
        return v


def test_webhook_signature_and_body(broker):
    finish(broker)
    transport = FakeTransport({"http://a": [200]})
    hook = WebhookDispatcher(broker, "s3cret", transport, sleep=lambda s: None)
    hook.add_endpoint("http://a")
    outbox = Outbox(broker)
    hook.attach(outbox)
    outbox.poll()
    assert outbox.flush() == {"webhooks": 1}
    url, body, headers = transport.calls[0]
    assert headers["X-Taskmill-Signature"] == sign("s3cret", body)
    assert verify_signature("s3cret", body, headers["X-Taskmill-Signature"])
    assert not verify_signature("other", body, headers["X-Taskmill-Signature"])
    doc = json.loads(body)
    assert doc["state"] == "done" and doc["result"] == {"done": True}
    assert hook.stats()["http://a"]["delivered"] == 1


def test_webhook_retries_with_backoff(broker):
    finish(broker)
    sleeps = []
    transport = FakeTransport({"http://a": [500, OSError("down"), 202]})
    hook = WebhookDispatcher(broker, "k", transport, backoff={"kind": "fixed", "delay": 2}, sleep=sleeps.append)
    hook.add_endpoint("http://a")
    outbox = Outbox(broker)
    hook.attach(outbox)
    outbox.poll()
    outbox.flush()
    assert sleeps == [2.0, 2.0] and len(transport.calls) == 3
    st = hook.stats()["http://a"]
    assert st["attempts"] == 3 and st["delivered"] == 1 and st["last_status"] == 202


def test_webhook_permanent_and_exhausted(broker):
    finish(broker)
    transport = FakeTransport({"http://bad": [404], "http://down": [503], "http://ok": [200]})
    hook = WebhookDispatcher(broker, "k", transport, attempts=3, sleep=lambda s: None)
    for url in ("http://bad", "http://down", "http://ok"):
        hook.add_endpoint(url)
    outbox = Outbox(broker, max_tries=1)
    hook.attach(outbox)
    outbox.poll()
    assert outbox.flush() == {"webhooks": 0}
    stats = hook.stats()
    assert stats["http://bad"]["attempts"] == 1 and stats["http://bad"]["failed"] == 1
    assert stats["http://down"]["attempts"] == 3
    assert stats["http://ok"]["delivered"] == 1
    assert outbox.counts()["webhooks"]["dropped"] == 1


# ---------------------------------------------------------------- sim

def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile(list(range(1, 101)), 95) == 95


def test_sim_single_worker_queueing():
    arrivals = [Arrival(0.0, "q", "k", 2.0), Arrival(0.0, "q", "k", 2.0), Arrival(1.0, "q", "k", 2.0)]
    r = simulate(arrivals, workers=1)
    assert (r.done, r.failed, r.retries) == (3, 0, 0)
    assert r.duration == 6.0 and r.waits == [0.0, 2.0, 3.0]
    assert r.wait_mean == pytest.approx(5 / 3) and r.run_mean == 2.0
    assert r.utilization == 1.0 and r.throughput == 0.5


def test_sim_more_workers_cuts_wait():
    arrivals = make_arrivals(40, rate=2.0, service_seconds=1.5, seed=3)
    slow, fast = simulate(arrivals, workers=1, seed=1), simulate(arrivals, workers=4, seed=1)
    assert fast.wait_p95 < slow.wait_p95 and fast.done == slow.done == 40


def test_sim_failures_are_deterministic():
    arrivals = make_arrivals(30, rate=1.0, service_seconds=0.5, fail_prob=0.5, seed=5)
    a, b = simulate(arrivals, workers=2, seed=9), simulate(arrivals, workers=2, seed=9)
    assert a.to_dict() == b.to_dict()
    assert a.retries > 0 and a.done + a.failed == 30
    assert a.to_dict() != simulate(arrivals, workers=2, seed=10).to_dict()
    assert "throughput" in a.render()


def test_sim_always_failing_exhausts_attempts():
    r = simulate([Arrival(0.0, "q", "k", 1.0, 1.0)], workers=1, max_attempts=3)
    assert (r.done, r.failed, r.retries) == (0, 1, 2)


# ---------------------------------------------------------------- top

def test_format_duration():
    assert [format_duration(x) for x in (None, 5, 75, 3725, -3)] == ["-", "5s", "1m15s", "1h02m", "-3s"]


def test_dashboard_render_and_rates(broker, clock):
    dash = Dashboard(broker)
    broker.enqueue("mail", "send")
    broker.enqueue("mail", "send")
    broker.enqueue("batch", "crunch", delay=60)
    broker.pause("batch")
    first = dash.render()
    assert "mail" in first and "batch" in first and "paused" in first
    assert "(no active leases)" in first and "(rates need two snapshots)" in first
    res = broker.reserve("w1")
    clock.advance(10)
    second = dash.render()
    assert res.job_id in second and "20s" in second
    assert "enqueued 0.00/s" in second and "reserved 0.10/s" in second
    assert "1 reserved" in second.splitlines()[0]


def test_dashboard_empty(broker):
    assert "(no queues)" in Dashboard(broker).render()


# ---------------------------------------------------------------- migrate

def legacy(i, status="queued", **kw):
    row = {"id": i, "queue": "mail", "type": "send", "args": {"n": i}, "prio": 5, "status": status,
           "tries": 0, "max_tries": 3, "not_before": 0, "created": 900000.0}
    row.update(kw)
    return row


def test_check_row_lists_all_problems():
    p = check_row(legacy(1, queue="Bad Queue", status="weird", prio="hi", max_tries=0))
    assert len(p) == 4
    assert check_row({"id": 1}) and check_row("nope") == ["row is not an object"]
    assert check_row(legacy(1, extra=1)) == ["unknown field extra"]


def test_migrate_dry_run_changes_nothing(broker):
    rows = [legacy(1), legacy(2, "ok"), legacy(3, queue="BAD")]
    r = migrate(rows, broker, dry_run=True)
    assert (r.imported, r.skipped_finished, r.ok) == (["1"], ["2"], False)
    assert r.errors[0].index == 2 and broker.stats()["jobs"] == 0
    assert "1 invalid" in r.render() and r.to_dict()["dry_run"] is True


def test_migrate_imports_waiting_rows(broker, clock):
    rows = [legacy(1, prio=42), legacy(2, "running", prio=-3), legacy(3, "scheduled", not_before=clock() + 500),
            legacy(4, "dead"), legacy(5, "cancelled"), legacy(6, "ok")]
    r = migrate(rows, broker)
    assert r.imported == ["1", "2", "3"] and r.skipped_finished == ["4", "5", "6"] and r.ok
    jobs = {j.payload["n"]: j for j in broker.jobs()}
    assert jobs[1].priority == 9 and jobs[2].priority == 0
    assert jobs[3].state == "delayed" and jobs[3].run_at == clock() + 500
    assert jobs[1].max_attempts == 3 and jobs[1].tags == ["legacy"]


def test_migrate_is_idempotent(broker):
    rows = [legacy(1), legacy(2)]
    migrate(rows, broker)
    again = migrate(rows, broker)
    assert again.imported == [] and again.duplicates == ["1", "2"] and broker.stats()["jobs"] == 2


def test_to_job_dict_maps_states():
    d = to_job_dict(legacy(7, "dead", tries=3), now=1_000_000.0)
    assert d["state"] == "failed" and d["finished_at"] == 1_000_000.0 and d["id"] == "legacy-7"
    assert to_job_dict(legacy(8, "ok"), 5.0)["state"] == "done"
    assert to_job_dict(legacy(9, "running"), 1_000_000.0)["state"] == "pending"
