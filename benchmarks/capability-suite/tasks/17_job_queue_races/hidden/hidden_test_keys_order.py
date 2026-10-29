"""Idempotency key normalisation, schedule keys, and delayed-job ordering."""

import subprocess
import sys
import unicodedata

import pytest

from hiddenkit import T0, make
from taskmill import InvalidKey, Schedule, Scheduler, normalize_key

# ===================================================================== keys

@pytest.mark.parametrize("a,b", [
    ("INV-1/23", "INV-12/3"),
    ("Order 12", "ORDER-12"),
    ("order-12", "order_12"),
    ("Order-12", "order-12"),
    ("abc", "ABC"),
    ("a.b", "ab"),
    ("x y", "xy"),
    ("ﬁle", "file"),            # ligature: NFKC would fold it, NFC does not
    ("１２３", "123"),           # full-width digits
    ("Straße", "STRASSE"),
    ("cron/daily-report/2026-10-21T06:00", "cron/daily.report/2026-10-21T06:00"),
])
def test_distinct_keys_stay_distinct(a, b):
    assert normalize_key(a) != normalize_key(b)


@pytest.mark.parametrize("a,b", [
    ("café", "café"),         # precomposed vs combining accent
    ("  order-17 ", "order-17"),
    ("\tINV-9 ", "INV-9"),
    ("Å", "Å"),               # angstrom sign NFC-normalises to A-ring
])
def test_equivalent_keys_match(a, b):
    assert normalize_key(a) == normalize_key(b)


@pytest.mark.parametrize("key", ["order-17", "INV-12/3", "Order 12", "cron/x/2026-01-01T00:00",
                                 "a:b:c", "émoji-🙂", "UPPER lower"])
def test_normalised_key_is_the_nfc_trimmed_text(key):
    assert normalize_key(key) == unicodedata.normalize("NFC", key).strip()


def test_invalid_keys_still_rejected():
    for bad in ["", "   ", "a\x00b", "a\nb", "x" * 201, 17, None]:
        with pytest.raises(InvalidKey):
            normalize_key(bad)
    assert normalize_key("x" * 200) == "x" * 200
    assert normalize_key("  " + "y" * 200 + "  ") == "y" * 200


def test_enqueue_distinct_invoice_keys_make_distinct_jobs():
    b, _ = make()
    a = b.enqueue("billing", "send_invoice", {"inv": "INV-12/3"}, idempotency_key="INV-12/3")
    c = b.enqueue("billing", "send_invoice", {"inv": "INV-1/23"}, idempotency_key="INV-1/23")
    assert a.created and c.created and a.job_id != c.job_id
    assert b.get(c.job_id).payload == {"inv": "INV-1/23"}
    assert b.metrics.value("jobs.deduplicated", queue="billing") == 0


def test_enqueue_case_sensitive_keys():
    b, _ = make()
    ids = {b.enqueue("orders", "k", idempotency_key=k).job_id for k in ["Order 12", "ORDER-12", "order 12"]}
    assert len(ids) == 3


def test_enqueue_same_key_dedups_with_nfc_and_whitespace():
    b, _ = make()
    a = b.enqueue("orders", "k", idempotency_key="café-1")
    c = b.enqueue("orders", "k", idempotency_key=" café-1 ")
    assert not c.created and c.job_id == a.job_id
    assert b.metrics.value("jobs.deduplicated", queue="orders") == 1


def test_stored_key_is_normalised_form():
    b, _ = make()
    jid = b.enqueue("q", "k", idempotency_key="  INV-12/3 ").job_id
    assert b.get(jid).idempotency_key == "INV-12/3"


def test_key_lifetime_unchanged():
    b, clock = make(dedup_window=100)
    a = b.enqueue("q", "k", idempotency_key="K-1").job_id
    r = b.reserve()
    b.ack(r.token, 1)
    clock.advance(99)
    assert b.enqueue("q", "k", idempotency_key="K-1").job_id == a
    clock.advance(1)
    n = b.enqueue("q", "k", idempotency_key="K-1")
    assert n.created and n.job_id != a


def test_keys_survive_recovery(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    a = b.enqueue("q", "k", idempotency_key="INV-12/3").job_id
    c = b.enqueue("q", "k", idempotency_key="INV-1/23").job_id
    b.close()
    b2, _ = make(str(tmp_path / "d"), clock=clock)
    assert b2.enqueue("q", "k", idempotency_key="INV-12/3").job_id == a
    assert b2.enqueue("q", "k", idempotency_key="INV-1/23").job_id == c
    assert b2.enqueue("q", "k", idempotency_key="inv-12/3").created
    b2.close()


def test_cli_key_command():
    p = subprocess.run([sys.executable, "-m", "taskmill", "key", "INV-1/23", " Order 12 "],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["'INV-1/23' -> 'INV-1/23'", "' Order 12 ' -> 'Order 12'"]


# ================================================================ schedules

def test_schedules_differing_by_punctuation_both_fire():
    b, clock = make(clock=None)
    day = 86400 * 20000  # 2024-10-04, midnight UTC
    s = Scheduler(b, [Schedule("daily-report", "reports", "echo", {"team": "finance"}, cron="0 6 * * *"),
                      Schedule("daily.report", "reports", "echo", {"team": "marketing"}, cron="0 6 * * *")],
                  start_at=day)
    fired = s.tick(now=day + 6 * 3600)
    assert sorted((f.schedule, f.created) for f in fired) == [("daily-report", True), ("daily.report", True)]
    payloads = sorted(j.payload["team"] for j in b.jobs(queue="reports"))
    assert payloads == ["finance", "marketing"]
    assert b.metrics.value("scheduler.fired", schedule="daily-report") == 1
    assert b.metrics.value("scheduler.fired", schedule="daily.report") == 1


def test_schedules_differing_by_case_both_fire():
    b, _ = make()
    s = Scheduler(b, [Schedule("Sync", "q", "echo", 1, every=60), Schedule("sync", "q", "echo", 2, every=60)],
                  start_at=0)
    fired = s.tick(now=60)
    assert all(f.created for f in fired) and len({f.job_id for f in fired}) == 2


def test_two_schedulers_same_schedule_fire_once():
    b, _ = make()
    mk = lambda: Scheduler(b, [Schedule("hourly-sync", "q", "echo", None, cron="@hourly")], start_at=0)
    f1 = mk().tick(now=3600)
    f2 = mk().tick(now=3600)
    assert [f.created for f in f1] == [True] and [f.created for f in f2] == [False]
    assert f1[0].job_id == f2[0].job_id
    assert len(b.jobs(queue="q")) == 1


def test_schedule_key_format_unchanged():
    s = Schedule("daily.report", "q", "echo", cron="0 6 * * *")
    assert s.key(6 * 3600) == "cron/daily.report/1970-01-01T06:00"
    assert Schedule("tick", "q", "echo", every=30).key(90) == "cron/tick/90"


# =================================================================== ordering

def test_due_delayed_job_not_starved_by_later_ready_work():
    b, clock = make()
    b.enqueue("q", "k", "early")
    late = b.enqueue("q", "k", "delayed", delay=5).job_id
    clock.advance(7)
    b.enqueue("q", "k", "arrived-after-due")
    clock.advance(1)
    got = [b.reserve().payload for _ in range(3)]
    assert got == ["early", "delayed", "arrived-after-due"]
    assert b.get(late).ready_at == T0 + 5


def test_due_retry_competes_with_busy_queue():
    b, clock = make(backoff={"kind": "fixed", "delay": 4.5})
    b.enqueue("refunds", "refund", "R1")
    r = b.reserve()
    b.nack(r.token, "provider timeout")          # due again at T0 + 4.5
    for i in range(10):                          # the queue never empties: one new job per second
        clock.advance(1)
        b.enqueue("refunds", "refund", f"bulk-{i}")
    got = []
    while True:
        nxt = b.reserve()
        if nxt is None:
            break
        got.append(nxt.payload)
    assert got == ["bulk-0", "bulk-1", "bulk-2", "bulk-3", "R1"] + [f"bulk-{i}" for i in range(4, 10)]


def test_due_retry_with_higher_priority_beats_waiting_low_priority():
    b, clock = make(backoff={"kind": "fixed", "delay": 3})
    b.enqueue("q", "k", "urgent", priority=0)
    for i in range(5):
        b.enqueue("q", "k", f"bulk-{i}", priority=9)
    r = b.reserve()
    assert r.payload == "urgent"
    b.nack(r.token, "flaky")
    clock.advance(3)
    assert b.reserve().payload == "urgent"


def test_promotion_uses_run_at_not_promotion_time():
    b, clock = make()
    a = b.enqueue("q", "k", "a", delay=10).job_id
    c = b.enqueue("q", "k", "c", delay=20).job_id
    clock.advance(25)
    b.enqueue("q", "k", "fresh")
    assert b.order("q")[:2] == [a, c]
    assert b.get(a).ready_at == T0 + 10 and b.get(c).ready_at == T0 + 20


def test_delayed_jobs_order_by_run_at_then_seq():
    b, clock = make()
    x = b.enqueue("q", "k", delay=5).job_id
    y = b.enqueue("q", "k", delay=5).job_id
    z = b.enqueue("q", "k", delay=2).job_id
    clock.advance(6)
    assert [b.reserve().job_id for _ in range(3)] == [z, x, y]


def test_not_yet_due_still_waits():
    b, clock = make()
    b.enqueue("q", "k", "now")
    b.enqueue("q", "k", "later", delay=10)
    clock.advance(9.9)
    assert b.reserve().payload == "now"
    assert b.reserve() is None
    clock.advance(0.1)
    assert b.reserve().payload == "later"


def test_cross_queue_due_delayed_beats_newer_ready():
    b, clock = make()
    b.enqueue("a", "k", "a-delayed", delay=5)
    clock.advance(6)
    b.enqueue("b", "k", "b-new")
    assert b.reserve().payload == "a-delayed"


def test_priority_still_wins_over_age():
    b, clock = make()
    b.enqueue("q", "k", "old-low", priority=9, delay=1)
    clock.advance(100)
    b.enqueue("q", "k", "new-high", priority=0)
    assert [b.reserve().payload for _ in range(2)] == ["new-high", "old-low"]


def test_expired_lease_ready_at_is_deadline():
    b, clock = make()
    b.enqueue("q", "k", "first")
    r = b.reserve()
    clock.advance(40)
    b.enqueue("q", "k", "second")
    b.reap()
    assert b.reserve().payload == "first"
    assert b.get(r.job_id).ready_at == r.deadline


def test_order_listing_reflects_due_jobs():
    b, clock = make()
    a = b.enqueue("q", "k", "a").job_id
    d = b.enqueue("q", "k", "d", delay=3).job_id
    clock.advance(4)
    c = b.enqueue("q", "k", "c").job_id
    assert b.order("q") == [a, d, c]
    b.reserve()
    assert b.order("q") == [d, c]


def test_ordering_after_recovery_matches(tmp_path):
    b, clock = make(str(tmp_path / "d"))
    b.enqueue("q", "k", "a")
    b.enqueue("q", "k", "d", delay=3)
    clock.advance(4)
    b.enqueue("q", "k", "c")
    b.reserve()
    fp = b.fingerprint()
    order = b.order("q")
    b.close()
    b2, _ = make(str(tmp_path / "d"), clock=clock)
    assert b2.fingerprint() == fp
    assert b2.order("q") == order
    assert [b2.reserve().payload for _ in range(2)] == ["d", "c"]
    b2.close()
