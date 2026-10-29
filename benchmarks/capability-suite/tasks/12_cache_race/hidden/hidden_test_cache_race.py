import random
import sys
import threading

import pytest

from pricecache import ManualClock, PriceServer, PriceService, ReadThroughCache, Stats, VersionedStore
from pricecache.keys import freeze, quote_key
from pricecache.pricing import PricingError, compute_quote
from pricecache.server import Request

WAIT = 10  # generous: every blocking wait in these tests normally takes milliseconds


def make_service(**kw):
    clock = kw.pop("clock", None) or ManualClock(1000.0)
    svc = PriceService(clock=clock, **kw)
    svc.set_region("US", "USD")
    svc.set_region("DE", "EUR", tax_bp=1900)
    svc.set_region("FR", "EUR", tax_bp=2000)
    svc.set_region("JP", "JPY", tax_bp=1000, rounding="whole")
    svc.set_fx("EUR", "0.5")
    svc.set_fx("JPY", "150")
    svc.set_price("A", 1000, tiers=[[10, 1000]])
    svc.set_price("B", 250)
    svc.set_price("C", 4000)
    return svc, clock


class Gate:
    """A store read hook that parks the first read of ``key`` (after arm) until released."""

    def __init__(self, store, key):
        self.key = key
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self._remove = store.add_read_hook(self)

    def __call__(self, key, record):
        if self.armed and key == self.key:
            self.armed = False
            self.entered.set()
            assert self.release.wait(WAIT), "gate never released"

    def close(self):
        self._remove()


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


def finish(t, out):
    t.join(WAIT)
    assert not t.is_alive(), "worker thread hung"
    if "error" in out:
        raise out["error"]
    return out.get("value")


# =========================================================== lost invalidation

def _blocking_loader(entered, release, value):
    def loader(key):
        v = value  # read "the data" before blocking, like a slow store read
        entered.set()
        assert release.wait(WAIT)
        return v
    return loader


@pytest.mark.parametrize("how", ["invalidate", "invalidate_where", "clear"])
def test_cache_invalidation_during_load_is_not_lost(how):
    c = ReadThroughCache("c", ttl=300, clock=ManualClock())
    entered, release = threading.Event(), threading.Event()
    t, out = run(c.get, "k", _blocking_loader(entered, release, "old"))
    assert entered.wait(WAIT)
    if how == "invalidate":
        c.invalidate("k")
    elif how == "invalidate_where":
        c.invalidate_where(lambda k: k == "k")
    else:
        c.clear()
    release.set()
    assert finish(t, out) == "old"  # the in-flight caller may see what it read
    assert "k" not in c
    assert c.get("k", lambda k: "new") == "new"
    assert c.get("k", lambda k: "newer") == "new"  # and the fresh value is cached


def test_unrelated_invalidation_does_not_discard_load():
    c = ReadThroughCache("c", ttl=300, clock=ManualClock())
    c.put("other", 1)
    entered, release = threading.Event(), threading.Event()
    t, out = run(c.get, "k", _blocking_loader(entered, release, "v"))
    assert entered.wait(WAIT)
    c.invalidate("other")
    c.invalidate_where(lambda k: k == "zzz")
    release.set()
    assert finish(t, out) == "v"
    assert c.peek("k") == "v"


def test_load_started_after_invalidation_is_cached():
    c = ReadThroughCache("c", ttl=300, clock=ManualClock())
    c.put("k", "old")
    c.invalidate("k")
    assert c.get("k", lambda k: "new") == "new"
    assert c.peek("k") == "new"
    assert c.stats.get("c.loads") == 1


def test_price_update_during_record_load_is_visible():
    svc, _ = make_service()
    assert svc.quote("A", "US").total_cents == 1000
    svc.records.clear()
    svc.quotes.clear()
    gate = Gate(svc.store, ("price", "A"))
    gate.armed = True
    t, out = run(svc.quote, "A", "US")
    assert gate.entered.wait(WAIT)
    svc.set_price("A", 2000)
    gate.release.set()
    assert finish(t, out).total_cents == 1000
    gate.close()
    assert svc.record("price", "A").value["base_cents"] == 2000
    assert svc.quote("A", "US").total_cents == 2000
    assert svc.quote("A", "US").price_version == svc.store.version(("price", "A"))


def test_price_update_during_quote_compute_is_visible():
    svc, _ = make_service()
    svc.quote("A", "US")  # price record now cached
    svc.quotes.clear()
    svc.records.invalidate(("region", "US"))
    gate = Gate(svc.store, ("region", "US"))
    gate.armed = True
    t, out = run(svc.quote, "A", "US", 3)
    assert gate.entered.wait(WAIT)
    svc.set_price("A", 1500)
    gate.release.set()
    assert finish(t, out).total_cents == 3000
    gate.close()
    assert svc.quote("A", "US", 3).total_cents == 4500


def test_fx_update_during_quote_compute_is_visible():
    svc, _ = make_service()
    assert svc.quote("C", "DE").total_cents == 2380
    svc.quotes.clear()
    svc.records.invalidate(("fx", "EUR"))
    gate = Gate(svc.store, ("fx", "EUR"))
    gate.armed = True
    t, out = run(svc.quote, "C", "DE")
    assert gate.entered.wait(WAIT)
    svc.set_fx("EUR", "1")
    gate.release.set()
    finish(t, out)
    gate.close()
    assert svc.quote("C", "DE").total_cents == 4760
    assert svc.quote("C", "FR").total_cents == 4800


def test_promo_update_during_quote_compute_is_visible():
    svc, _ = make_service()
    svc.set_promo("SALE", 1000, skus=["B"])
    assert svc.quote("B", "US", 10, options={"promo": "SALE"}).total_cents == 2250
    svc.quotes.clear()
    svc.records.invalidate(("promo", "SALE"))
    gate = Gate(svc.store, ("promo", "SALE"))
    gate.armed = True
    t, out = run(svc.quote, "B", "US", 10, "web", {"promo": "SALE"})
    assert gate.entered.wait(WAIT)
    svc.set_promo("SALE", 1000, skus=["B"], active=False)
    gate.release.set()
    finish(t, out)
    gate.close()
    assert svc.quote("B", "US", 10, options={"promo": "SALE"}).total_cents == 2500


def test_out_of_order_writers_do_not_leave_old_record_cached():
    svc, _ = make_service()
    svc.quote("A", "US")
    hold = threading.Event()
    parked = threading.Event()

    def slow_listener(rec):
        if rec.key == ("price", "A") and rec.value["base_cents"] == 1100:
            parked.set()
            assert hold.wait(WAIT)

    unsub = svc.store.subscribe(slow_listener)
    t, out = run(svc.set_price, "A", 1100)
    assert parked.wait(WAIT)
    svc.set_price("A", 1200)
    hold.set()
    finish(t, out)
    unsub()
    assert svc.record("price", "A").value["base_cents"] == 1200
    assert svc.quote("A", "US").total_cents == 1200


def test_write_warms_record_cache():
    svc, _ = make_service()
    svc.set_price("A", 1700)
    reads = svc.store.reads
    rec = svc.record("price", "A")
    assert rec.value["base_cents"] == 1700 and rec.version == 2
    assert svc.store.reads == reads


# ================================================= concurrency is not serialized

def test_loads_for_different_skus_run_concurrently():
    svc, _ = make_service()
    svc.records.clear()
    barrier = threading.Barrier(2, timeout=WAIT)

    def hook(key, rec):
        if key in (("price", "A"), ("price", "B")):
            barrier.wait()

    remove = svc.store.add_read_hook(hook)
    ta = run(svc.quote, "A", "US")
    tb = run(svc.quote, "B", "US")
    assert finish(*ta).total_cents == 1000
    assert finish(*tb).total_cents == 250
    remove()


def test_write_does_not_wait_for_slow_load():
    svc, _ = make_service()
    svc.records.clear()
    gate = Gate(svc.store, ("price", "A"))
    gate.armed = True
    t, out = run(svc.quote, "A", "US")
    assert gate.entered.wait(WAIT)
    w = run(svc.set_price, "A", 3000)
    w[0].join(5)
    writer_done = not w[0].is_alive()
    gate.release.set()
    finish(t, out)
    finish(*w)
    gate.close()
    assert writer_done, "set_price blocked behind an in-flight load"
    assert svc.quote("A", "US").total_cents == 3000


def test_server_serves_other_requests_while_one_is_slow():
    svc, _ = make_service()
    svc.records.clear()
    gate = Gate(svc.store, ("price", "C"))
    gate.armed = True
    with PriceServer(svc, workers=2) as srv:
        slow = srv.submit(Request("quote", {"sku": "C", "region": "US"}))
        assert gate.entered.wait(WAIT)
        assert srv.call("quote", wait=5, sku="B", region="US")["total_cents"] == 250
        gate.release.set()
        assert slow.result(WAIT)["total_cents"] == 4000
    gate.close()


# ================================================================ cache keys

@pytest.mark.parametrize("a,b", [
    ({"gift_wrap": True}, {"rush": True}),
    ({"member": True}, {"rush": True}),
    ({"gift_wrap": True, "member": False}, {"gift_wrap": False, "member": True}),
    ({"promo": "X"}, {"engraving": "X"}),
])
def test_different_options_do_not_share_a_key(a, b):
    assert quote_key("B", "US", 1, "web", a) != quote_key("B", "US", 1, "web", b)
    assert freeze(a) != freeze(b)


def test_different_options_get_different_quotes():
    svc, _ = make_service()
    assert svc.quote("B", "US", options={"gift_wrap": True}).total_cents == 749
    assert svc.quote("B", "US", options={"rush": True}).total_cents == 288
    assert svc.quote("B", "US", options={"member": True}).total_cents == 238
    assert svc.quote("B", "US", options={"rush": True, "member": False}).total_cents == 288
    assert svc.quote("B", "US", options={"member": True, "rush": False}).total_cents == 238
    q1 = svc.quote("B", "US", options={"engraving": {"lines": ["hi", ""]}})
    q2 = svc.quote("B", "US", options={"engraving": {"lines": ["hi", "yo"]}})
    assert (q1.total_cents, q2.total_cents) == (500, 750)


def test_promo_codes_do_not_share_a_key():
    svc, _ = make_service()
    svc.set_promo("TEN", 1000)
    svc.set_promo("TWENTY", 2000)
    assert svc.quote("C", "US", options={"promo": "TEN"}).total_cents == 3600
    assert svc.quote("C", "US", options={"promo": "TWENTY"}).total_cents == 3200


def test_equal_options_still_share_a_key():
    k1 = quote_key("A", " us ", 2, "Web", {"rush": True, "engraving": {"lines": ["a"]}, "gift_wrap": True})
    k2 = quote_key("A", "US", 2, "web", {"gift_wrap": True, "rush": True, "engraving": {"lines": ["a"]}})
    assert k1 == k2 and hash(k1) == hash(k2)
    assert quote_key("A", "US", 1, "web", None) == quote_key("A", "US", 1, "web", {})
    assert freeze({"x": [1, 2]}) != freeze({"x": [2, 1]})
    svc, _ = make_service()
    svc.quote("B", "US", options={"rush": True, "gift_wrap": True})
    svc.quote("B", "US", options={"gift_wrap": True, "rush": True})
    assert svc.stats.get("quotes.hits") == 1


# ===================================================================== stats

class BarrierClock:
    """A clock whose first two calls (from two threads) meet at a barrier.

    A correct Stats never loses an update however its clock behaves.
    """

    def __init__(self):
        self.barrier = threading.Barrier(2, timeout=1.0)
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.calls += 1
            gated = self.calls <= 2
        if gated:
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return 42.0


def test_stats_incr_does_not_lose_updates():
    s = Stats(clock=BarrierClock())
    ts = [run(s.incr, "x", 1), run(s.incr, "x", 2)]
    for t in ts:
        finish(*t)
    assert s.get("x") == 3
    assert s.last_updated("x") == 42.0


def test_stats_observe_does_not_lose_updates():
    s = Stats(clock=BarrierClock())
    ts = [run(s.observe, "lat", 1.0), run(s.observe, "lat", 2.0)]
    for t in ts:
        finish(*t)
    assert s.snapshot("lat") == {"lat.count": 2, "lat.sum": 3.0, "lat.max": 2.0}


def test_stats_hammer_exact_totals():
    s = Stats()
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        def work(i):
            for j in range(3000):
                s.incr("a.n")
                s.incr(f"a.t{i % 3}", 2)
                s.observe("lat", float(j % 7))
        ts = [run(work, i) for i in range(8)]
        for t in ts:
            finish(*t)
    finally:
        sys.setswitchinterval(old)
    assert s.get("a.n") == 24000
    assert sum(s.get(f"a.t{k}") for k in range(3)) == 48000
    assert s.get("lat.count") == 24000
    assert s.get("lat.sum") == 8 * sum(float(j % 7) for j in range(3000))
    assert s.get("lat.max") == 6.0


def test_stats_api_regression():
    clock = ManualClock(5)
    s = Stats(clock=clock)
    s.incr("a.x")
    clock.advance(1)
    s.incr("a.x", 4)
    s.incr("b.y")
    assert s.get("a.x") == 5 and s.get("nope") == 0 and s.get("nope", None) is None
    assert s.last_updated("a.x") == 6 and s.last_updated("zzz") is None
    assert s.snapshot("a") == {"a.x": 5}
    assert s.snapshot() == {"a.x": 5, "b.y": 1}
    s.reset("a")
    assert s.snapshot() == {"b.y": 1}
    s.reset()
    assert s.snapshot() == {}


# ============================================================ hammer, end to end

def expected_total(store, sku, region, qty, channel, options):
    region_rec = store.get(("region", region))
    fx = None
    cur = region_rec.value["currency"]
    if cur != "USD":
        fx = store.get(("fx", cur))
    promo = store.get(("promo", options["promo"].upper())) if options.get("promo") else None
    return compute_quote(sku, region, qty, channel, options, store.get(("price", sku)),
                         region_rec, fx, promo).total_cents


def test_server_hammer_consistency_and_exact_counters():
    svc, _ = make_service(clock=ManualClock(0))
    skus = [f"S{i}" for i in range(6)]
    for i, s in enumerate(skus):
        svc.set_price(s, 1000 + i)
    svc.set_promo("P", 500)
    regions = ["US", "DE", "JP"]
    option_sets = [None, {"rush": True}, {"gift_wrap": True}, {"member": True}, {"promo": "P"}]
    rng = random.Random(1234)
    reqs = []
    for n in range(3000):
        r = rng.random()
        if r < 0.08:
            reqs.append(Request("set_price", {"sku": rng.choice(skus), "base_cents": rng.randint(500, 5000)}))
        elif r < 0.10:
            reqs.append(Request("set_fx", {"currency": "EUR", "rate": rng.choice(["0.5", "0.8", "1.1"])}))
        elif r < 0.11:
            reqs.append(Request("set_promo", {"code": "P", "discount_bp": rng.choice([500, 900])}))
        elif r < 0.12:
            reqs.append(Request("nope", {}))
        else:
            reqs.append(Request("quote", {"sku": rng.choice(skus), "region": rng.choice(regions),
                                          "qty": rng.choice([1, 2, 12]),
                                          "options": rng.choice(option_sets)}))
    n_quotes = sum(r.op == "quote" for r in reqs)
    n_bad = sum(r.op == "nope" for r in reqs)
    calls_before = svc.stats.get("service.quote_calls")
    hm_before = svc.stats.get("quotes.hits") + svc.stats.get("quotes.misses")
    reads_before = svc.store.reads

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        with PriceServer(svc, workers=8, trace_reads=True) as srv:
            futs = [srv.submit(r) for r in reqs]
            for f in futs:
                f.exception(WAIT * 3)
            store_reads = svc.store.reads - reads_before
            traced = sum(v for k, v in svc.stats.snapshot("store").items() if k.startswith("store.reads."))
    finally:
        sys.setswitchinterval(old)

    st = svc.stats
    assert st.get("server.requests") == len(reqs)
    assert st.get("server.errors") == n_bad
    assert st.get("server.ok") == len(reqs) - n_bad
    assert st.get("server.op.quote") == n_quotes
    assert st.get("server.latency.count") == len(reqs)
    assert st.get("service.quote_calls") - calls_before == n_quotes
    assert st.get("quotes.hits") + st.get("quotes.misses") - hm_before == n_quotes
    assert traced == store_reads

    for sku in skus:
        for region in regions:
            for qty in (1, 2, 12):
                for opts in option_sets:
                    got = svc.quote(sku, region, qty, "web", opts).total_cents
                    want = expected_total(svc.store, sku, region, qty, "web", dict(opts or {}))
                    assert got == want, (sku, region, qty, opts)


# =================================================== regression: cache basics

def test_ttl_boundaries_and_none():
    clock = ManualClock()
    c = ReadThroughCache("c", ttl=5, clock=clock)
    c.put("a", 1)
    clock.advance(4.999)
    assert c.peek("a") == 1
    clock.advance(0.001)
    assert c.peek("a") is None
    assert c.get("a", lambda k: 2) == 2
    z = ReadThroughCache("z", ttl=0, clock=clock)
    assert z.get("a", lambda k: 1) == 1 and len(z) == 0
    n = ReadThroughCache("n", ttl=None, clock=clock)
    n.put("a", 1)
    clock.advance(1e9)
    assert n.get("a", lambda k: 2) == 1
    with pytest.raises(ValueError):
        ReadThroughCache("bad", ttl=-1)
    with pytest.raises(ValueError):
        ReadThroughCache("bad", maxsize=0)


def test_lru_eviction_and_expired_first():
    clock = ManualClock()
    c = ReadThroughCache("c", ttl=10, maxsize=3, clock=clock)
    c.put("a", 1)
    clock.advance(5)
    c.put("b", 2)
    c.put("c", 3)
    assert c.get("a", None) == 1  # a is now most recently used
    c.put("d", 4)  # evicts b
    assert c.keys() == ["c", "a", "d"]
    assert c.stats.get("c.evictions") == 1
    clock.advance(5)  # a expires (stored at 0), c and d are fresh
    c.put("e", 5)
    assert sorted(c.keys()) == ["c", "d", "e"]
    assert c.stats.get("c.evictions") == 1
    assert c.stats.get("c.expired") == 1


def test_load_error_not_cached_and_counted():
    c = ReadThroughCache("c", clock=ManualClock())

    def boom(k):
        raise LookupError(k)

    with pytest.raises(LookupError):
        c.get("k", boom)
    assert "k" not in c
    assert c.get("k", lambda k: "ok") == "ok"
    s = c.stats
    assert (s.get("c.misses"), s.get("c.loads"), s.get("c.load_errors"), s.get("c.hits")) == (2, 1, 1, 0)
    c.get("k", boom)
    assert s.get("c.hits") == 1


def test_invalidation_counts_only_removed_entries():
    c = ReadThroughCache("c", clock=ManualClock())
    for k in "abc":
        c.put(k, k)
    assert c.invalidate("zz") is False
    assert c.invalidate_where(lambda k: k in "ab") == 2
    assert c.clear() == 1
    assert c.stats.get("c.invalidations") == 3


# ================================================ regression: service + server

def test_quote_values_and_invalidation_scope():
    svc, clock = make_service()
    assert svc.quote("C", "DE").total_cents == 2380
    assert svc.quote("C", "JP").total_cents == 660000
    assert svc.quote("A", "US", 10).total_cents == 9000
    assert svc.quote("A", "US", 1, "partner").total_cents == 1080
    us_before = svc.stats.get("quotes.misses")
    svc.quote("C", "US")
    svc.set_fx("EUR", "1")
    assert "C" in {k.sku for k in svc.quotes.keys()}
    assert any(k.region == "US" for k in svc.quotes.keys())
    assert all(k.region not in ("DE", "FR") for k in svc.quotes.keys())
    assert svc.quote("C", "DE").total_cents == 4760
    assert svc.quote("C", "JP").total_cents == 660000
    assert svc.stats.get("quotes.misses") == us_before + 2
    svc.delete_price("C")
    with pytest.raises(PricingError):
        svc.quote("C", "US")
    clock.advance(1)


def test_quote_ttl_regression():
    svc, clock = make_service(quote_ttl=300, record_ttl=30)
    svc.quote("A", "US")
    clock.advance(299.9)
    svc.quote("A", "US")
    assert svc.stats.get("quotes.hits") == 1
    clock.advance(0.1)
    svc.quote("A", "US")
    assert svc.stats.get("quotes.misses") == 2
    assert svc.stats.get("quotes.expired") == 1


def test_stats_report_shape():
    svc, _ = make_service()
    svc.quote("A", "US")
    svc.quote("A", "US")
    rep = svc.stats_report()
    assert set(rep) == {"records", "quotes", "store"}
    assert rep["quotes"]["hits"] == 1 and rep["quotes"]["misses"] == 1
    assert rep["quotes"]["hit_ratio"] == 0.5
    assert rep["quotes"]["size"] == 1
    assert set(rep["records"]) == {"hits", "misses", "hit_ratio", "size", "evictions", "invalidations"}
    assert rep["store"]["writes"] == svc.store.writes


def test_server_regression():
    svc, _ = make_service()
    with PriceServer(svc, workers=3) as srv:
        assert srv.call("quote", sku="B", region="us", options={"rush": True})["total_cents"] == 288
        assert srv.call("record", kind="price", name="B")["base_cents"] == 250
        assert srv.call("record", kind="price", name="ZZ") is None
        assert srv.call("set_price", sku="B", base_cents=300) == 2
        assert srv.call("quote", sku="B", region="US")["total_cents"] == 300
        with pytest.raises(ValueError):
            srv.call("bogus")
    assert svc.stats.get("server.requests") == 6
    assert svc.stats.get("server.ok") == 5
    assert svc.stats.get("server.errors") == 1
    assert svc.stats.get("server.latency.count") == 6
