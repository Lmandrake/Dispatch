"""WAL: replay order, torn tails, and recovery fidelity."""

import os

import pytest

from hiddenkit import WAIT, Park, finish, make, run
from taskmill import WalCorrupt
from taskmill import wal as walmod


def data(tmp_path):
    return str(tmp_path / "d")


def seg(path, n=1):
    return os.path.join(path, "wal", f"wal-{n:06d}.log")


def park_append(b, op, **match):
    p = Park(lambda record, **_: record["op"] == op and all(record.get(k) == v for k, v in match.items()))
    remove = b.hooks.add("wal.append", p)
    return p, remove


def reopen(path, clock):
    b, _ = make(path, clock=clock)
    return b


# ============================================================ replay order

def test_out_of_order_pause_resume_replays_in_seq_order(tmp_path):
    path = data(tmp_path)
    b, clock = make(path)
    b.enqueue("q", "k")
    p, remove = park_append(b, "pause", paused=True)
    t = run(b.pause, "q")
    assert p.entered.wait(WAIT)
    b.resume("q")                      # its record reaches the file first
    p.release.set()
    finish(*t)
    remove()
    assert b.queue_stats("q")["paused"] is False
    fp = b.fingerprint()
    b.close()
    assert walmod.verify(os.path.join(path, "wal"))["file_order_is_seq_order"] is False
    b2 = reopen(path, clock)
    assert b2.queue_stats("q")["paused"] is False
    assert b2.fingerprint() == fp
    assert b2.reserve() is not None
    b2.close()


def test_out_of_order_priority_changes(tmp_path):
    path = data(tmp_path)
    b, clock = make(path)
    jid = b.enqueue("q", "k", priority=5).job_id
    p, remove = park_append(b, "priority", priority=9)
    t = run(b.set_priority, jid, 9)
    assert p.entered.wait(WAIT)
    b.set_priority(jid, 1)
    p.release.set()
    finish(*t)
    remove()
    assert b.get(jid).priority == 1
    b.close()
    b2 = reopen(path, clock)
    assert b2.get(jid).priority == 1
    b2.close()


def test_reserve_record_written_before_its_enqueue(tmp_path):
    path = data(tmp_path)
    b, clock = make(path)
    p, remove = park_append(b, "enqueue")
    t = run(b.enqueue, "q", "k", {"n": 1})
    assert p.entered.wait(WAIT)
    r = b.reserve(worker="fast")           # the job is already reservable in memory
    assert r is not None and r.payload == {"n": 1}
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp
    b2.ack(r.token, "ok")
    assert b2.result(r.job_id).result == "ok"
    b2.close()


def test_ack_record_overtakes_heartbeat(tmp_path):
    path = data(tmp_path)
    b, clock = make(path)
    b.enqueue("q", "k")
    r = b.reserve()
    p, remove = park_append(b, "heartbeat")
    t = run(b.heartbeat, r.token)
    assert p.entered.wait(WAIT)
    b.ack(r.token, 5)
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp and b2.result(r.job_id).result == 5
    b2.close()


def test_out_of_order_across_segments(tmp_path):
    path = data(tmp_path)
    b, clock = make(path, wal_segment_bytes=256)
    jid = b.enqueue("q", "k", "x" * 50).job_id
    p, remove = park_append(b, "priority", priority=9)
    t = run(b.set_priority, jid, 9)
    assert p.entered.wait(WAIT)
    b.set_priority(jid, 2)
    for i in range(5):
        b.enqueue("q", "k", "y" * 50)
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    assert len(walmod.list_segments(os.path.join(path, "wal"))) > 1
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp and b2.get(jid).priority == 2
    b2.close()


def test_out_of_order_after_checkpoint(tmp_path):
    path = data(tmp_path)
    b, clock = make(path)
    jid = b.enqueue("q", "k").job_id
    b.checkpoint()
    p, remove = park_append(b, "pause", paused=True)
    t = run(b.pause, "q")
    assert p.entered.wait(WAIT)
    b.resume("q")
    b.set_priority(jid, 0)
    p.release.set()
    finish(*t)
    remove()
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp and b2.recovery.snapshot_seq == 1
    b2.close()


def test_replay_ordering_in_recover_check(tmp_path):
    from taskmill import BrokerConfig
    from taskmill.recovery import check
    path = data(tmp_path)
    b, clock = make(path)
    b.enqueue("q", "k")
    p, remove = park_append(b, "enqueue")
    t = run(b.enqueue, "q", "k")
    assert p.entered.wait(WAIT)
    r = b.reserve()
    r2 = b.reserve()
    p.release.set()
    finish(*t)
    remove()
    b.close()
    rep = check(path, BrokerConfig(visibility_timeout=30))
    assert rep["states"] == {"reserved": 2} and rep["records_replayed"] == 4


# =============================================================== torn tails

def _write_some(path, clock=None, n=3):
    b, clock = make(path, clock=clock)
    ids = [b.enqueue("q", "k", i).job_id for i in range(n)]
    b.close()
    return ids, clock


@pytest.mark.parametrize("tail", [b"TMW1\x00", b"TMW1\x00\x00\x00\x40\x00\x00\x00\x00{\"seq\"", b"TM"])
def test_torn_tail_then_more_appends_then_restart(tmp_path, tail):
    path = data(tmp_path)
    ids, clock = _write_some(path)
    good = os.path.getsize(seg(path))
    with open(seg(path), "ab") as fh:
        fh.write(tail)
    b = reopen(path, clock)
    assert b.recovery.torn_tail["offset"] == good
    new = b.enqueue("q", "k", "after-crash").job_id
    fp = b.fingerprint()
    b.close()
    b2 = reopen(path, clock)                # the routine restart that used to fail
    assert b2.fingerprint() == fp
    assert b2.get(new).payload == "after-crash"
    assert b2.recovery.torn_tail is None
    b2.close()


def test_torn_tail_with_bad_crc_at_eof(tmp_path):
    path = data(tmp_path)
    ids, clock = _write_some(path)
    raw = bytearray(open(seg(path), "rb").read())
    raw[-2] ^= 0x55                          # damage the last record's payload: CRC mismatch at EOF
    open(seg(path), "wb").write(bytes(raw))
    b = reopen(path, clock)
    assert b.recovery.torn_tail["reason"] == "bad crc"
    assert [j.id for j in b.jobs()] == ids[:2]
    b.enqueue("q", "k", "x")
    b.close()
    b2 = reopen(path, clock)
    assert len(b2.jobs()) == 3 and b2.recovery.torn_tail is None
    b2.close()


def test_torn_tail_is_cut_from_the_file(tmp_path):
    path = data(tmp_path)
    _, clock = _write_some(path)
    good = os.path.getsize(seg(path))
    with open(seg(path), "ab") as fh:
        fh.write(b"TMW1\x00\x00")
    b = reopen(path, clock)
    assert os.path.getsize(seg(path)) == good
    rep = walmod.verify(os.path.join(path, "wal"))
    assert rep["ok"] and rep["torn_tail"] is None and rep["records"] == 3
    b.close()


def test_torn_tail_repeated_crashes(tmp_path):
    path = data(tmp_path)
    _, clock = _write_some(path, n=1)
    for i in range(3):
        with open(seg(path), "ab") as fh:
            fh.write(b"TMW1\x00\x00\x00")
        b = reopen(path, clock)
        b.enqueue("q", "k", i)
        b.close()
    b = reopen(path, clock)
    assert len(b.jobs()) == 4
    b.close()


def test_real_corruption_still_detected(tmp_path):
    path = data(tmp_path)
    _, clock = _write_some(path)
    raw = bytearray(open(seg(path), "rb").read())
    raw[0:4] = b"XXXX"
    open(seg(path), "wb").write(bytes(raw))
    with pytest.raises(WalCorrupt):
        reopen(path, clock)


def test_corruption_in_older_segment_detected(tmp_path):
    path = data(tmp_path)
    b, clock = make(path, wal_segment_bytes=200)
    for i in range(6):
        b.enqueue("q", "k", "z" * 60)
    b.close()
    segs = walmod.list_segments(os.path.join(path, "wal"))
    assert len(segs) >= 2
    with open(segs[0].path, "ab") as fh:
        fh.write(b"TMW1\x00")
    with pytest.raises(WalCorrupt):
        reopen(path, clock)


def test_torn_tail_after_rotation_only_newest_cut(tmp_path):
    path = data(tmp_path)
    b, clock = make(path, wal_segment_bytes=200)
    for i in range(6):
        b.enqueue("q", "k", "z" * 60)
    b.close()
    segs = walmod.list_segments(os.path.join(path, "wal"))
    sizes = [s.size for s in segs]
    with open(segs[-1].path, "ab") as fh:
        fh.write(b"TMW1")
    b = reopen(path, clock)
    b.enqueue("q", "k", "new")
    b.close()
    now = walmod.list_segments(os.path.join(path, "wal"))
    assert [s.size for s in now[:len(sizes) - 1]] == sizes[:-1]
    b = reopen(path, clock)
    assert len(b.jobs()) == 7
    b.close()


# ======================================================== recovery fidelity

def test_full_lifecycle_recovers_identically(tmp_path):
    path = data(tmp_path)
    b, clock = make(path, backoff={"kind": "exponential", "base": 2, "factor": 3, "max": 50, "jitter": "full"},
                    max_attempts=3)
    a = b.enqueue("q", "k", {"a": 1}, idempotency_key="A-1").job_id
    c = b.enqueue("q", "k", {"c": 1}, priority=1, tags=["x"]).job_id
    d = b.enqueue("other", "k", None, delay=100).job_id
    r = b.reserve()
    b.nack(r.token, RuntimeError("boom"))
    r = b.reserve()
    b.heartbeat(r.token, extend=45)
    clock.advance(100)
    b.reap()
    b.pause("other")
    b.cancel(d)
    b.retry(d)
    b.resume("other")
    while True:
        r = b.reserve()
        if r is None:
            break
        b.ack(r.token, {"done": r.job_id})
    b.checkpoint()
    e = b.enqueue("q", "k", "post").job_id
    fp = b.fingerprint()
    st = b.stats()
    b.close()
    b2 = reopen(path, clock)
    assert b2.fingerprint() == fp
    assert b2.stats() == st
    assert b2.enqueue("q", "k", idempotency_key="A-1").job_id == a
    assert b2.enqueue("q", "k").job_id == "job-5"
    b2.close()
