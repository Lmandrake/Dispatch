import pytest

from taskmill import (Broker, BrokerConfig, InvalidTransition, LeaseLost, ManualClock, UnknownJob,
                      ValidationError)
from taskmill.config import QueueConfig


def test_enqueue_reserve_ack(broker):
    e = broker.enqueue("email", "send", {"to": "a@example.org"})
    assert e.created and e.job_id == "job-1"
    r = broker.reserve(worker="w1")
    assert r.job_id == "job-1" and r.attempt == 1 and r.payload == {"to": "a@example.org"}
    assert broker.get("job-1").state == "reserved"
    broker.ack(r.token, {"sent": True})
    res = broker.result("job-1")
    assert res.ok and res.result == {"sent": True} and res.attempts == 1


def test_reserve_empty_returns_none(broker):
    assert broker.reserve() is None


def test_priority_order(broker):
    broker.enqueue("q", "k", 1, priority=9)
    broker.enqueue("q", "k", 2, priority=0)
    broker.enqueue("q", "k", 3, priority=5)
    broker.enqueue("q", "k", 4, priority=0)
    got = [broker.reserve().payload for _ in range(4)]
    assert got == [2, 4, 3, 1]


def test_fifo_within_priority(broker, clock):
    for i in range(5):
        broker.enqueue("q", "k", i)
        clock.advance(1)
    assert [broker.reserve().payload for _ in range(5)] == [0, 1, 2, 3, 4]


def test_delayed_job_not_ready_until_run_at(broker, clock):
    broker.enqueue("q", "k", "later", delay=10)
    assert broker.reserve() is None
    clock.advance(9.9)
    assert broker.reserve() is None
    clock.advance(0.1)
    assert broker.reserve().payload == "later"


def test_nack_schedules_retry_with_backoff(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    assert broker.nack(r.token, "boom") == "delayed"
    job = broker.get(r.job_id)
    assert job.state == "delayed" and job.run_at == clock() + 1.0
    assert job.errors[-1]["message"] == "boom"
    clock.advance(1.0)
    r2 = broker.reserve()
    assert r2.job_id == r.job_id and r2.attempt == 2


def test_nack_after_max_attempts_fails(broker, clock):
    broker.enqueue("q", "k", None, max_attempts=2)
    r = broker.reserve()
    broker.nack(r.token, "one")
    clock.advance(100)
    r = broker.reserve()
    assert broker.nack(r.token, "two") == "failed"
    res = broker.result(r.job_id)
    assert res.state == "failed" and res.error == "two" and res.attempts == 2


def test_permanent_nack(broker):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    assert broker.nack(r.token, "bad input", permanent=True) == "failed"


def test_nack_retry_in(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    broker.nack(r.token, "later", retry_in=42)
    assert broker.get(r.job_id).run_at == clock() + 42


def test_ack_with_unknown_token(broker):
    with pytest.raises(LeaseLost):
        broker.ack("nope")


def test_double_ack_rejected(broker):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    broker.ack(r.token, 1)
    with pytest.raises(LeaseLost, match="released"):
        broker.ack(r.token, 2)
    assert broker.result(r.job_id).result == 1


def test_lease_expiry_redelivers(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve(worker="a")
    clock.advance(30)
    assert broker.reap() == [r.job_id]
    job = broker.get(r.job_id)
    assert job.state == "pending" and job.errors[-1]["message"] == "lease expired"
    r2 = broker.reserve(worker="b")
    assert r2.job_id == r.job_id and r2.token != r.token and r2.attempt == 2


def test_ack_after_expiry_rejected(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    clock.advance(31)
    with pytest.raises(LeaseLost, match="expired"):
        broker.ack(r.token, 1)


def test_heartbeat_extends(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    clock.advance(20)
    d = broker.heartbeat(r.token)
    assert d == clock() + 30
    clock.advance(20)
    assert broker.reap() == []
    broker.ack(r.token, "ok")


def test_heartbeat_capped(clock):
    b = Broker(None, BrokerConfig(visibility_timeout=30, max_visibility_timeout=50), clock=clock)
    b.enqueue("q", "k", None)
    r = b.reserve()
    clock.advance(25)
    assert b.heartbeat(r.token) == r.deadline - 30 + 50


def test_reserve_reaps_inline(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    clock.advance(30)
    r2 = broker.reserve()
    assert r2.job_id == r.job_id


def test_cancel(broker):
    a = broker.enqueue("q", "k", None).job_id
    assert broker.cancel(a) is True
    assert broker.cancel(a) is False
    assert broker.reserve() is None
    assert broker.get(a).state == "cancelled"


def test_cancel_reserved_releases_lease(broker):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    broker.cancel(r.job_id)
    with pytest.raises(LeaseLost):
        broker.heartbeat(r.token)


def test_operator_retry(broker):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    broker.nack(r.token, "x", permanent=True)
    broker.retry(r.job_id)
    job = broker.get(r.job_id)
    assert job.state == "pending" and job.attempts == 0
    with pytest.raises(InvalidTransition):
        broker.retry(r.job_id)


def test_set_priority(broker):
    a = broker.enqueue("q", "k", "a", priority=5).job_id
    broker.enqueue("q", "k", "b", priority=5)
    broker.set_priority(a, 9)
    assert broker.reserve().payload == "b"


def test_pause_resume(broker):
    broker.enqueue("q", "k", None)
    broker.pause("q")
    assert broker.reserve() is None
    broker.resume("q")
    assert broker.reserve() is not None


def test_queue_filter(broker):
    broker.enqueue("a", "k", 1)
    broker.enqueue("b", "k", 2)
    assert broker.reserve(queues=["b"]).payload == 2


def test_validation(broker):
    with pytest.raises(ValidationError):
        broker.enqueue("Bad Name", "k")
    with pytest.raises(ValidationError):
        broker.enqueue("q", "k", priority=10)
    with pytest.raises(ValidationError):
        broker.enqueue("q", "k", {1, 2})
    with pytest.raises(ValidationError):
        broker.enqueue("q", "k", float("nan"))
    with pytest.raises(UnknownJob):
        broker.get("job-99")


def test_idempotency_same_key(broker):
    a = broker.enqueue("q", "k", 1, idempotency_key="order-17")
    b = broker.enqueue("q", "k", 2, idempotency_key="order-17")
    assert a.created and not b.created and a.job_id == b.job_id


def test_idempotency_scoped_by_queue(broker):
    a = broker.enqueue("q1", "k", idempotency_key="x-1")
    b = broker.enqueue("q2", "k", idempotency_key="x-1")
    assert a.job_id != b.job_id


def test_wait_returns_result(broker):
    import threading
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    t = threading.Timer(0.05, lambda: broker.ack(r.token, 7))
    t.start()
    view = broker.wait(r.job_id, timeout=5)
    assert view.result == 7
    t.join()


def test_wait_timeout(broker):
    a = broker.enqueue("q", "k").job_id
    assert broker.wait(a, timeout=0.05) is None


def test_purge(broker, clock):
    broker.enqueue("q", "k", None)
    r = broker.reserve()
    broker.ack(r.token)
    clock.advance(7 * 86400)
    assert broker.purge() == [r.job_id]
    with pytest.raises(UnknownJob):
        broker.get(r.job_id)


def test_rate_limit(clock):
    cfg = BrokerConfig(queues={"slow": QueueConfig(rate=1.0, burst=2)})
    b = Broker(None, cfg, clock=clock)
    for i in range(4):
        b.enqueue("slow", "k", i)
    assert b.reserve() is not None and b.reserve() is not None
    assert b.reserve() is None
    clock.advance(1)
    assert b.reserve().payload == 2


def test_order_listing(broker, clock):
    a = broker.enqueue("q", "k", priority=3).job_id
    b = broker.enqueue("q", "k", priority=1).job_id
    c = broker.enqueue("q", "k", delay=5).job_id
    assert broker.order("q") == [b, a, c]


def test_stats(broker):
    broker.enqueue("q", "k")
    broker.enqueue("q", "k")
    broker.reserve()
    st = broker.stats()
    assert st["jobs"] == 2 and st["states"]["pending"] == 1 and st["states"]["reserved"] == 1
    assert broker.queue_stats("q")["reserved"] == 1


def test_closed_broker(clock):
    from taskmill import BrokerClosed
    b = Broker(None, clock=clock)
    b.close()
    with pytest.raises(BrokerClosed):
        b.enqueue("q", "k")
