import threading

import pytest

from pricecache import ManualClock, PriceServer, PriceService, ReadThroughCache, Stats, VersionedStore
from pricecache.keys import quote_key
from pricecache.pricing import PricingError, round_for_region, tier_discount_bp
from pricecache.store import ConflictError


def make_service(**kw):
    clock = ManualClock(1000.0)
    svc = PriceService(clock=clock, **kw)
    svc.set_region("US", "USD")
    svc.set_region("DE", "EUR", tax_bp=1900)
    svc.set_fx("EUR", "0.5")
    svc.set_price("A", 1000, tiers=[[10, 1000]])
    svc.set_price("B", 250)
    return svc, clock


# ------------------------------------------------------------------- store

def test_store_versions_and_history():
    s = VersionedStore(clock=ManualClock())
    assert s.get("k") is None
    assert s.put("k", 1).version == 1
    assert s.put("k", 2).version == 2
    assert s.get("k").value == 2
    assert [r.value for r in s.history("k")] == [1, 2]
    with pytest.raises(ConflictError):
        s.compare_and_put("k", 3, expected_version=1)
    assert s.compare_and_put("k", 3, expected_version=2).version == 3
    assert s.delete("k").deleted
    assert list(s.keys()) == []


def test_store_listeners_and_read_hooks():
    s = VersionedStore()
    seen, reads = [], []
    unsub = s.subscribe(lambda rec: seen.append((rec.key, rec.version)))
    remove = s.add_read_hook(lambda key, rec: reads.append(key))
    s.put("x", 1)
    s.get("x")
    unsub()
    remove()
    s.put("x", 2)
    s.get("x")
    assert seen == [("x", 1)]
    assert reads == ["x"]


# ------------------------------------------------------------------- cache

def test_cache_ttl_and_lru():
    clock = ManualClock()
    c = ReadThroughCache("c", ttl=10, maxsize=2, clock=clock)
    loads = []

    def loader(k):
        loads.append(k)
        return k.upper()

    assert c.get("a", loader) == "A"
    assert c.get("a", loader) == "A"
    clock.advance(9.999)
    assert c.get("a", loader) == "A"
    clock.advance(0.001)
    assert c.get("a", loader) == "A"
    assert loads == ["a", "a"]
    c.get("b", loader)
    c.get("a", loader)
    c.get("c", loader)  # evicts b, the least recently used
    assert set(c.keys()) == {"a", "c"}
    assert c.stats.get("c.evictions") == 1
    assert c.stats.get("c.expired") == 1


def test_cache_invalidate():
    c = ReadThroughCache("c", clock=ManualClock())
    c.get("a", str.upper)
    c.get("b", str.upper)
    assert c.invalidate("a") is True
    assert c.invalidate("a") is False
    assert c.invalidate_where(lambda k: k == "b") == 1
    assert len(c) == 0
    assert c.stats.get("c.invalidations") == 2


def test_cache_loads_for_different_keys_run_in_parallel():
    c = ReadThroughCache("c")
    barrier = threading.Barrier(2, timeout=10)

    def loader(k):
        barrier.wait()
        return k

    results = []
    threads = [threading.Thread(target=lambda k=k: results.append(c.get(k, loader))) for k in "xy"]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    assert sorted(results) == ["x", "y"]


# ----------------------------------------------------------------- pricing

def test_pricing_helpers():
    assert tier_discount_bp([[10, 500], [50, 1200]], 9) == 0
    assert tier_discount_bp([[10, 500], [50, 1200]], 50) == 1200
    assert round_for_region(1234, "five_cents") == 1235
    assert round_for_region(1250, "whole") == 1200


def test_quotes():
    svc, _ = make_service()
    assert svc.quote("A", "US").total_cents == 1000
    assert svc.quote("A", "US", qty=10).total_cents == 9000
    assert svc.quote("A", "us", channel=" APP ").total_cents == 980
    assert svc.quote("B", "DE").total_cents == 149  # 250 * 0.5 * 1.19
    assert svc.quote("B", "US", options={"gift_wrap": True}).total_cents == 749
    with pytest.raises(PricingError):
        svc.quote("NOPE", "US")


def test_writes_invalidate_quotes():
    svc, _ = make_service()
    assert svc.quote("A", "US").total_cents == 1000
    svc.set_price("A", 1100)
    assert svc.quote("A", "US").total_cents == 1100
    assert svc.quote("B", "DE").total_cents == 149
    svc.set_fx("EUR", "1")
    assert svc.quote("B", "DE").total_cents == 298


def test_option_order_does_not_matter():
    k1 = quote_key("A", "US", 1, "web", {"rush": True, "gift_wrap": True})
    k2 = quote_key("A", "us", 1, "web", {"gift_wrap": True, "rush": True})
    assert k1 == k2 and hash(k1) == hash(k2)


def test_quote_ttl():
    svc, clock = make_service(quote_ttl=300)
    svc.quote("A", "US")
    svc.quote("A", "US")
    assert svc.stats.get("quotes.hits") == 1
    clock.advance(300)
    svc.quote("A", "US")
    assert svc.stats.get("quotes.misses") == 2


# ------------------------------------------------------------ stats/server

def test_stats_basics():
    s = Stats(clock=ManualClock(5))
    s.incr("a.x")
    s.incr("a.x", 2)
    s.observe("lat", 0.5)
    s.observe("lat", 1.5)
    assert s.get("a.x") == 3
    assert s.last_updated("a.x") == 5
    assert s.snapshot("lat") == {"lat.count": 2, "lat.sum": 2.0, "lat.max": 1.5}
    s.reset("a")
    assert s.get("a.x") == 0


def test_server_roundtrip():
    svc, _ = make_service()
    svc.records.clear()
    with PriceServer(svc, workers=3, trace_reads=True) as srv:
        assert srv.call("quote", sku="A", region="US")["total_cents"] == 1000
        assert srv.call("set_price", sku="A", base_cents=1500) == 2
        assert srv.call("quote", sku="A", region="US")["total_cents"] == 1500
        with pytest.raises(KeyError):
            srv.call("quote", region="US")
        report = srv.call("stats")
    assert report["quotes"]["misses"] == 2
    assert svc.stats.get("server.requests") == 5
    assert svc.stats.get("server.errors") == 1
    assert svc.stats.get("store.reads.price") == 1
    assert svc.stats.get("store.reads.region") == 1
