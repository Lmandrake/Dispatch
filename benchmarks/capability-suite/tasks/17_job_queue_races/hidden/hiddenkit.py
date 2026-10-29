"""Shared helpers for the hidden tests (not a test module)."""

import threading

from taskmill import Broker, BrokerConfig, ManualClock

WAIT = 10  # generous: every blocking wait here normally takes milliseconds
T0 = 1_000_000.0


def make(data_dir=None, clock=None, **cfg):
    clock = clock or ManualClock(T0)
    cfg.setdefault("visibility_timeout", 30)
    return Broker(data_dir, BrokerConfig(**cfg), clock=clock), clock


def run(fn, *args, **kw):
    out = {}

    def target():
        try:
            out["value"] = fn(*args, **kw)
        except BaseException as exc:  # noqa: BLE001
            out["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t, out


def finish(t, out, timeout=WAIT):
    t.join(timeout)
    assert not t.is_alive(), "thread hung (is a broker lock held across a hook or I/O?)"
    if "error" in out:
        raise out["error"]
    return out.get("value")


def outcome(t, out, timeout=WAIT):
    """('ok', value) or ('error', exception) for a finished thread."""
    t.join(timeout)
    assert not t.is_alive(), "thread hung"
    if "error" in out:
        return "error", out["error"]
    return "ok", out.get("value")


class Park:
    """A hook that parks the first matching call until released."""

    def __init__(self, match=lambda **kw: True):
        self.match = match
        self.armed = True
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, **kw):
        with self.lock:
            go = self.armed and self.match(**kw)
            if go:
                self.armed = False
        if go:
            self.entered.set()
            assert self.release.wait(WAIT), "park never released"


class BarrierClock:
    """A clock whose first two calls (from two threads) meet at a barrier.

    Correct metrics never lose an update however their clock behaves.
    """

    def __init__(self, value=42.0):
        self.barrier = threading.Barrier(2, timeout=1.0)
        self.calls = 0
        self.lock = threading.Lock()
        self.value = value

    def __call__(self):
        with self.lock:
            self.calls += 1
            gated = self.calls <= 2
        if gated:
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return self.value
