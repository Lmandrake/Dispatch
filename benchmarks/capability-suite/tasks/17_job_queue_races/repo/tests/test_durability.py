import os

import pytest

from taskmill import Broker, BrokerConfig, ManualClock
from taskmill import wal as walmod


def reopen(path, clock):
    return Broker(path, BrokerConfig(visibility_timeout=30), clock=clock)


def test_recover_after_close(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    a = b.enqueue("q", "k", {"n": 1}, idempotency_key="key-1").job_id
    b.enqueue("q", "k", 2, delay=50)
    r = b.reserve()
    b.ack(r.token, "done")
    c = b.enqueue("q", "k", 3).job_id
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp
    assert b2.get(a).result == "done"
    assert b2.enqueue("q", "k", idempotency_key="key-1").job_id == a
    assert b2.enqueue("q", "k").job_id == "job-4"
    assert b2.recovery.records_replayed > 0
    b2.close()


def test_reserved_job_survives_restart(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    b.enqueue("q", "k")
    r = b.reserve()
    b.close()
    b2 = reopen(path, clock)
    b2.ack(r.token, 1)
    assert b2.result(r.job_id).ok
    b2.close()


def test_checkpoint_and_segments(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    for i in range(10):
        b.enqueue("q", "k", i)
    snap = b.checkpoint()
    assert os.path.basename(snap) == "snapshot-000000000010.json"
    for i in range(3):
        b.enqueue("q", "k", i)
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp
    assert b2.recovery.snapshot_seq == 10 and b2.recovery.records_replayed == 3
    b2.close()


def test_wal_record_framing(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    b.enqueue("q", "k", "x")
    b.close()
    seg = os.path.join(path, "wal", "wal-000001.log")
    data = open(seg, "rb").read()
    assert data[:4] == b"TMW1"
    res = walmod.scan(os.path.join(path, "wal"))
    assert [r["op"] for r in res.records] == ["enqueue"]
    assert res.torn is None


def test_wal_corruption_detected(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    b.enqueue("q", "k", "x")
    b.enqueue("q", "k", "y")
    b.close()
    seg = os.path.join(path, "wal", "wal-000001.log")
    data = bytearray(open(seg, "rb").read())
    data[20] ^= 0xFF
    open(seg, "wb").write(bytes(data))
    with pytest.raises(walmod.WalCorrupt):
        reopen(path, clock)


def test_torn_tail_reported_and_ignored(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    b.enqueue("q", "k", "x")
    b.close()
    seg = os.path.join(path, "wal", "wal-000001.log")
    with open(seg, "ab") as fh:
        fh.write(b"TMW1\x00\x00")
    b2 = reopen(path, clock)
    assert b2.recovery.torn_tail["reason"] == "short header"
    assert len(b2.jobs()) == 1
    b2.close()


def test_verify(tmp_path, clock):
    path = str(tmp_path / "d")
    b = reopen(path, clock)
    b.enqueue("q", "k")
    b.close()
    rep = walmod.verify(os.path.join(path, "wal"))
    assert rep["ok"] and rep["records"] == 1 and rep["file_order_is_seq_order"]
