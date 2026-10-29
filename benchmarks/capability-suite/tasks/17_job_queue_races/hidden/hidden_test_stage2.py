"""Stage 2: fair queues (docs/FAIRNESS.md) and `taskmill doctor` (docs/DOCTOR.md)."""

import json
import os
import subprocess
import sys

import pytest

from hiddenkit import make
from taskmill import ValidationError
from taskmill import wal as walmod
from taskmill.admin import AdminApp
from taskmill.config import QueueConfig


def fair_broker(weights=None, default_weight=1, **extra):
    qc = QueueConfig(fair=True, tenant_weights=weights, default_weight=default_weight)
    queues = {"billing": qc}
    queues.update(extra.pop("queues", {}))
    return make(queues=queues, **extra)


def drain(b, n=None, queues=None):
    out = []
    while n is None or len(out) < n:
        r = b.reserve(queues=queues)
        if r is None:
            break
        out.append(r)
    return out


# ================================================================ fairness

def test_spec_example_order():
    b, clock = fair_broker({"acme": 3, "globex": 1}, default_weight=2)
    for t in ("acme", "globex", "initech"):
        for i in range(6):
            b.enqueue("billing", "k", f"{t}-{i}", tenant=t)
    got = [r.tenant for r in drain(b, 12)]
    assert got == ["acme"] * 3 + ["globex"] + ["initech"] * 2 + ["acme"] * 3 + ["globex"] + ["initech"] * 2


def test_within_tenant_order_is_priority_then_age():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "a-low", tenant="a", priority=9)
    clock.advance(1)
    b.enqueue("billing", "k", "a-high", tenant="a", priority=0)
    b.enqueue("billing", "k", "b-1", tenant="b", priority=9)
    assert [r.payload for r in drain(b)] == ["a-high", "b-1", "a-low"]


def test_priority_does_not_cross_tenants():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "a", tenant="a", priority=9)
    b.enqueue("billing", "k", "z", tenant="z", priority=0)
    b.enqueue("billing", "k", "z2", tenant="z", priority=0)
    assert [r.payload for r in drain(b)] == ["a", "z", "z2"]


def test_tenant_without_work_is_skipped():
    b, clock = fair_broker({"a": 2, "b": 2, "c": 2})
    for p in ("a1", "a2", "a3", "a4"):
        b.enqueue("billing", "k", p, tenant="a")
    b.enqueue("billing", "k", "c1", tenant="c")
    assert [r.payload for r in drain(b)] == ["a1", "a2", "c1", "a3", "a4"]


def test_turn_wraps_and_current_tenant_comes_last():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "b1", tenant="b")
    b.enqueue("billing", "k", "c1", tenant="c")
    assert drain(b, 1)[0].payload == "b1"
    b.enqueue("billing", "k", "a1", tenant="a")
    b.enqueue("billing", "k", "b2", tenant="b")
    assert [r.payload for r in drain(b)] == ["c1", "a1", "b2"]


def test_untenanted_jobs_are_tenant_default():
    b, clock = fair_broker({"default": 2})
    b.enqueue("billing", "k", "d1")
    b.enqueue("billing", "k", "d2")
    b.enqueue("billing", "k", "d3")
    b.enqueue("billing", "k", "acme1", tenant="acme")
    assert [r.payload for r in drain(b)] == ["acme1", "d1", "d2", "d3"]


def test_new_work_for_current_tenant_continues_turn():
    b, clock = fair_broker({"a": 3})
    b.enqueue("billing", "k", "a1", tenant="a")
    b.enqueue("billing", "k", "b1", tenant="b")
    assert drain(b, 1)[0].payload == "a1"
    b.enqueue("billing", "k", "a2", tenant="a")
    assert [r.payload for r in drain(b)] == ["a2", "b1"]


def test_queue_stats_turn():
    b, clock = fair_broker({"a": 2})
    b.enqueue("billing", "k", tenant="a")
    b.enqueue("other", "k")
    st = b.queue_stats("billing")
    assert st["fair"] is True and st["turn"] is None
    drain(b, 1, queues=["billing"])
    assert b.queue_stats("billing")["turn"] == ["a", 1]
    assert b.queue_stats("other")["fair"] is False and "turn" not in b.queue_stats("other")


def test_order_listing_simulates_turns_without_advancing():
    b, clock = fair_broker({"a": 2})
    ids = {}
    for p, t in (("a1", "a"), ("a2", "a"), ("a3", "a"), ("b1", "b"), ("b2", "b")):
        ids[p] = b.enqueue("billing", "k", p, tenant=t).job_id
    later = b.enqueue("billing", "k", "later", tenant="b", delay=100).job_id
    want = [ids[p] for p in ("a1", "a2", "b1", "a3", "b2")] + [later]
    assert b.order("billing") == want
    assert b.order("billing") == want
    assert b.queue_stats("billing")["turn"] is None
    assert [r.job_id for r in drain(b)] == want[:-1]


def test_due_delayed_job_counts_as_ready_in_fair_queue():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "b-delayed", tenant="b", delay=5)
    b.enqueue("billing", "k", "a1", tenant="a")
    b.enqueue("billing", "k", "a2", tenant="a")
    clock.advance(5)
    assert [r.payload for r in drain(b)] == ["a1", "b-delayed", "a2"]


def test_peeking_from_other_queue_does_not_advance_turn():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "a1", tenant="a", priority=5)
    b.enqueue("billing", "k", "b1", tenant="b", priority=5)
    b.enqueue("urgent", "k", "u", priority=0)
    assert drain(b, 1)[0].payload == "u"
    assert b.queue_stats("billing")["turn"] is None
    assert [r.payload for r in drain(b)] == ["a1", "b1"]


def test_fair_queue_competes_with_its_next_job():
    b, clock = fair_broker()
    b.enqueue("billing", "k", "a-low", tenant="a", priority=7)
    b.enqueue("billing", "k", "b-high", tenant="b", priority=1)
    b.enqueue("plain", "k", "plain-mid", priority=4)
    assert [r.payload for r in drain(b)] == ["plain-mid", "a-low", "b-high"]


def test_paused_fair_queue_keeps_turn():
    b, clock = fair_broker({"a": 2})
    for p in ("a1", "a2"):
        b.enqueue("billing", "k", p, tenant="a")
    b.enqueue("billing", "k", "b1", tenant="b")
    drain(b, 1)
    b.pause("billing")
    assert b.reserve() is None
    b.resume("billing")
    assert [r.payload for r in drain(b)] == ["a2", "b1"]


def test_non_fair_queue_ignores_tenants():
    b, clock = make()
    b.enqueue("q", "k", "b1", tenant="b")
    b.enqueue("q", "k", "b2", tenant="b")
    b.enqueue("q", "k", "a1", tenant="a")
    assert [r.payload for r in drain(b)] == ["b1", "b2", "a1"]


def test_turn_not_persisted(tmp_path):
    path = str(tmp_path / "d")
    from taskmill import Broker, BrokerConfig
    cfg = BrokerConfig(visibility_timeout=30, queues={"billing": QueueConfig(fair=True)})
    b, clock = make(path, queues={"billing": QueueConfig(fair=True)})
    for p, t in (("a1", "a"), ("a2", "a"), ("b1", "b")):
        b.enqueue("billing", "k", p, tenant=t)
    assert drain(b, 1)[0].payload == "a1"
    b.close()
    b2 = Broker(path, cfg, clock=clock)
    assert b2.queue_stats("billing")["turn"] is None
    assert [r.payload for r in drain(b2)] == ["a2", "b1"]
    b2.close()


def test_tenant_validation_and_fields():
    b, clock = make()
    for bad in ("Acme", "", "a b", "-x", "x" * 65, 5):
        with pytest.raises(ValidationError):
            b.enqueue("q", "k", tenant=bad)
    jid = b.enqueue("q", "k", tenant="acme-eu.1").job_id
    j = b.get(jid)
    assert j.tenant == "acme-eu.1" and j.to_dict()["tenant"] == "acme-eu.1" and j.summary()["tenant"] == "acme-eu.1"
    assert b.reserve().tenant == "acme-eu.1"
    b.enqueue("q", "k", tenant="globex")
    b.enqueue("q", "k")
    assert [x.id for x in b.jobs(tenant="globex")] == ["job-2"]
    assert len(b.jobs()) == 3


def test_tenant_survives_recovery(tmp_path):
    path = str(tmp_path / "d")
    b, clock = make(path)
    jid = b.enqueue("q", "k", tenant="acme").job_id
    b.checkpoint()
    jid2 = b.enqueue("q", "k", tenant="globex").job_id
    b.close()
    b2, _ = make(path, clock=clock)
    assert b2.get(jid).tenant == "acme" and b2.get(jid2).tenant == "globex"
    b2.close()


def test_admin_tenant():
    b, clock = make()
    app = AdminApp(b)
    st, doc = app("POST", "/queues/q/jobs", {"kind": "k", "tenant": "acme"})
    assert st == 201
    app("POST", "/queues/q/jobs", {"kind": "k"})
    st, doc2 = app("GET", "/jobs?tenant=acme")
    assert [j["id"] for j in doc2["jobs"]] == [doc["job_id"]] and doc2["jobs"][0]["tenant"] == "acme"
    assert app("POST", "/queues/q/jobs", {"kind": "k", "tenant": "BAD"})[0] == 400


def test_fair_config_roundtrip():
    from taskmill import BrokerConfig
    from taskmill.errors import ConfigError
    cfg = BrokerConfig.from_dict({"queues": {"billing": {"fair": True, "tenant_weights": {"acme": 3},
                                                          "default_weight": 2}}})
    assert cfg.queues["billing"].fair and cfg.queues["billing"].tenant_weights == {"acme": 3}
    with pytest.raises(ConfigError):
        BrokerConfig.from_dict({"queues": {"billing": {"fair": True, "tenant_weights": {"acme": 0}}}})


def cli(*args):
    p = subprocess.run([sys.executable, "-m", "taskmill", *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def test_cli_tenant(tmp_path):
    d = str(tmp_path / "data")
    assert cli("enqueue", d, "q", "echo", "--tenant", "acme")[0] == 0
    assert cli("enqueue", d, "q", "echo")[0] == 0
    rc, out, _ = cli("list", d, "--tenant", "acme", "--json")
    doc = json.loads(out)
    assert rc == 0 and [j["id"] for j in doc] == ["job-1"] and doc[0]["tenant"] == "acme"


# ================================================================== doctor

TOK = {k: (k * 24)[:24] for k in "abcdefgh"}


def enq(seq, jid, at=0.0):
    return {"seq": seq, "op": "enqueue", "job": {"id": jid, "queue": "q", "kind": "k", "payload": None,
                                                 "priority": 5, "state": "pending", "seq": seq,
                                                 "enqueued_at": at, "run_at": at, "ready_at": at}}


def rec(seq, op, jid=None, tok=None, **kw):
    r = {"seq": seq, "op": op}
    if jid is not None:
        r["id"] = jid
    if tok is not None:
        r["token"] = TOK[tok]
    r.update(kw)
    return r


def write_wal(path, records, segments=1, tail=b""):
    d = os.path.join(path, "wal")
    os.makedirs(d, exist_ok=True)
    per = max(1, -(-len(records) // segments)) if records else 1
    chunks = [records[i:i + per] for i in range(0, len(records), per)] or [[]]
    for n, chunk in enumerate(chunks, start=1):
        with open(os.path.join(d, walmod.segment_name(n)), "wb") as fh:
            for r in chunk:
                fh.write(walmod.encode_record(r))
            if n == len(chunks):
                fh.write(tail)
    return path


SCENARIO = [
    enq(1, "job-1"),
    enq(2, "job-2"),
    rec(3, "reserve", "job-1", "a", worker="w1", at=1.0, deadline=31.0),
    rec(4, "expire", "job-1", "a", at=31.0, to="pending"),
    rec(5, "reserve", "job-1", "b", worker="w2", at=32.0, deadline=62.0),
    rec(6, "heartbeat", "job-1", "a", deadline=70.0),
    rec(7, "ack", "job-1", "a", result=1, at=40.0),
    rec(8, "ack", "job-1", "b", result=2, at=41.0),
    rec(9, "cancel", "job-2", at=42.0),
    rec(10, "reserve", "job-2", "c", worker="w3", at=42.0, deadline=72.0),
    rec(11, "ack", "job-2", "c", result=3, at=43.0),
    rec(12, "reserve", "job-9", "d", worker="w4", at=44.0, deadline=74.0),
    rec(13, "ack", "job-9", "e", result=4, at=45.0),
]

SCENARIO_TEXT = """doctor: 13 record(s), seq 1..13, 2 job(s), 4 anomaly(ies)
6 job-1 stale-heartbeat token aaaaaa (current: bbbbbb)
7 job-1 stale-ack token aaaaaa (current: bbbbbb)
8 job-1 duplicate-ack first ack at seq 7
10 job-2 reserve-after-cancel cancelled at seq 9
"""


def test_doctor_text_report(tmp_path):
    d = write_wal(str(tmp_path / "d"), SCENARIO)
    rc, out, err = cli("doctor", d)
    assert out == SCENARIO_TEXT
    assert rc == 3


def test_doctor_records_out_of_file_order(tmp_path):
    shuffled = SCENARIO[6:] + SCENARIO[:6]
    d = write_wal(str(tmp_path / "d"), shuffled, segments=3)
    rc, out, _ = cli("doctor", d)
    assert out == SCENARIO_TEXT and rc == 3


def test_doctor_json(tmp_path):
    d = write_wal(str(tmp_path / "d"), SCENARIO)
    rc, out, _ = cli("doctor", d, "--json")
    doc = json.loads(out)
    assert rc == 3
    assert out == json.dumps(doc, sort_keys=True, indent=2) + "\n"
    assert doc["records"] == 13 and doc["min_seq"] == 1 and doc["max_seq"] == 13 and doc["jobs"] == 2
    assert doc["torn_tail"] is None
    assert doc["anomalies"][0] == {"seq": 6, "job_id": "job-1", "kind": "stale-heartbeat",
                                   "detail": "token aaaaaa (current: bbbbbb)"}
    assert [a["kind"] for a in doc["anomalies"]] == ["stale-heartbeat", "stale-ack", "duplicate-ack",
                                                     "reserve-after-cancel"]


def test_doctor_clean_log(tmp_path):
    d = write_wal(str(tmp_path / "d"), [enq(1, "job-1"), rec(2, "reserve", "job-1", "a", at=0, deadline=30),
                                        rec(3, "heartbeat", "job-1", "a", deadline=40),
                                        rec(4, "ack", "job-1", "a", result=None, at=5)])
    rc, out, _ = cli("doctor", d)
    assert rc == 0 and out == "doctor: 4 record(s), seq 1..4, 1 job(s), 0 anomaly(ies)\n"


def test_doctor_empty_log(tmp_path):
    d = write_wal(str(tmp_path / "d"), [])
    rc, out, _ = cli("doctor", d)
    assert rc == 0 and out == "doctor: 0 record(s), seq -..-, 0 job(s), 0 anomaly(ies)\n"
    rc, out, _ = cli("doctor", d, "--json")
    doc = json.loads(out)
    assert doc["min_seq"] is None and doc["max_seq"] is None and doc["anomalies"] == []


def test_doctor_stale_after_release_and_retry(tmp_path):
    recs = [enq(1, "job-1"),
            rec(2, "reserve", "job-1", "a", at=0, deadline=30),
            rec(3, "retry", "job-1", "a", run_at=5, error="x", at=1),
            rec(4, "fail", "job-1", "a", error="y", at=2),
            rec(5, "reserve", "job-1", "b", at=6, deadline=36),
            rec(6, "release", "job-1", "b", at=7),
            rec(7, "release", "job-1", "b", at=8)]
    d = write_wal(str(tmp_path / "d"), recs)
    rc, out, _ = cli("doctor", d)
    assert out.splitlines()[1:] == ["4 job-1 stale-fail token aaaaaa (current: none)",
                                    "7 job-1 stale-release token bbbbbb (current: none)"]
    assert rc == 3


def test_doctor_requeue_and_purge(tmp_path):
    recs = [enq(1, "job-1"), enq(2, "job-2"),
            rec(3, "reserve", "job-1", "a", at=0, deadline=30),
            rec(4, "ack", "job-1", "a", result=1, at=1),
            rec(5, "cancel", "job-2", at=1),
            rec(6, "requeue", "job-2", at=2),
            rec(7, "reserve", "job-2", "b", at=3, deadline=33),
            rec(8, "ack", "job-2", "b", result=2, at=4),
            rec(9, "purge", ids=["job-1"]),
            rec(10, "ack", "job-1", "c", result=3, at=5)]
    d = write_wal(str(tmp_path / "d"), recs)
    rc, out, _ = cli("doctor", d)
    assert rc == 0 and out == "doctor: 10 record(s), seq 1..10, 2 job(s), 0 anomaly(ies)\n"


def test_doctor_same_seq_sorted_by_kind(tmp_path):
    recs = [enq(1, "job-1"), rec(2, "reserve", "job-1", "a", at=0, deadline=30),
            rec(3, "ack", "job-1", "a", result=1, at=1),
            rec(4, "ack", "job-1", "b", result=2, at=2)]
    d = write_wal(str(tmp_path / "d"), recs)
    rc, out, _ = cli("doctor", d)
    assert out.splitlines()[1:] == ["4 job-1 duplicate-ack first ack at seq 3",
                                    "4 job-1 stale-ack token bbbbbb (current: none)"]


def test_doctor_torn_tail_reported_not_repaired(tmp_path):
    d = write_wal(str(tmp_path / "d"), SCENARIO[:2], tail=b"TMW1\x00")
    seg = os.path.join(d, "wal", "wal-000001.log")
    size = os.path.getsize(seg)
    rc, out, _ = cli("doctor", d)
    lines = out.splitlines()
    assert lines[0] == "doctor: 2 record(s), seq 1..2, 2 job(s), 0 anomaly(ies)"
    assert lines[-1] == f"torn tail: short header at byte {size - 5} of wal-000001.log"
    assert rc == 0 and os.path.getsize(seg) == size
    rc, out, _ = cli("doctor", d, "--json")
    assert json.loads(out)["torn_tail"]["reason"] == "short header"


def test_doctor_corrupt_log(tmp_path):
    d = write_wal(str(tmp_path / "d"), SCENARIO, segments=2)
    first = os.path.join(d, "wal", "wal-000001.log")
    raw = bytearray(open(first, "rb").read())
    raw[0:4] = b"ZZZZ"
    open(first, "wb").write(bytes(raw))
    rc, out, err = cli("doctor", d)
    assert rc == 1 and err.startswith("taskmill: ")


def test_doctor_library_api(tmp_path):
    from taskmill import doctor
    anomalies = doctor.diagnose(list(reversed(SCENARIO)))
    assert [(a["seq"], a["kind"]) for a in anomalies] == [(6, "stale-heartbeat"), (7, "stale-ack"),
                                                          (8, "duplicate-ack"), (10, "reserve-after-cancel")]
    d = write_wal(str(tmp_path / "d"), SCENARIO)
    doc = doctor.examine(d)
    assert doc["jobs"] == 2 and len(doc["anomalies"]) == 4


def test_doctor_on_real_broker_log_is_clean(tmp_path):
    path = str(tmp_path / "d")
    b, clock = make(path)
    b.enqueue("q", "k")
    b.enqueue("q", "k")
    r = b.reserve()
    clock.advance(31)
    r2 = b.reserve()
    from taskmill import LeaseLost
    with pytest.raises(LeaseLost):
        b.ack(r.token, 1)
    with pytest.raises(LeaseLost):
        b.heartbeat(r.token)
    b.ack(r2.token, 2)
    b.cancel("job-2")
    b.close()
    rc, out, _ = cli("doctor", path)
    assert rc == 0 and out.startswith("doctor: 6 record(s), seq 1..6, 2 job(s), 0 anomaly(ies)")
