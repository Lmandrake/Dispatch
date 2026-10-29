import time

import pytest
from ttlcache import TTLLRUCache


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def mk(maxsize=3, ttl=10):
    clk = Clock()
    return TTLLRUCache(maxsize, ttl, clock=clk), clk


def test_validation():
    for args in [(0, 1), (-1, 1), (1, 0), (1, -5)]:
        with pytest.raises(ValueError):
            TTLLRUCache(*args)
    c, _ = mk()
    with pytest.raises(ValueError):
        c.set("a", 1, ttl=0)


def test_lru_eviction_and_get_refreshes():
    c, _ = mk(3)
    c["a"] = 1; c["b"] = 2; c["c"] = 3
    assert c["a"] == 1          # a becomes MRU
    c["d"] = 4                  # evicts b
    assert "b" not in c
    assert c.keys() == ["c", "a", "d"]
    assert len(c) == 3


def test_peek_contains_keys_do_not_refresh():
    c, _ = mk(2)
    c["a"] = 1; c["b"] = 2
    assert c.peek("a") == 1
    assert "a" in c
    c.keys(); len(c)
    c["c"] = 3
    assert "a" not in c and c.keys() == ["b", "c"]


def test_expiry_boundary():
    c, clk = mk(3, ttl=10)
    c["a"] = 1
    clk.t = 109.999
    assert c.get("a") == 1
    clk.t = 110.0
    assert c.get("a") is None
    assert c.get("a", "dflt") == "dflt"
    assert "a" not in c
    assert len(c) == 0
    with pytest.raises(KeyError):
        c["a"]


def test_read_does_not_extend_life_but_set_does():
    c, clk = mk(3, ttl=10)
    c["a"] = 1
    clk.t = 105; c.get("a")
    clk.t = 110
    assert "a" not in c
    c["b"] = 1
    clk.t = 115; c["b"] = 2
    clk.t = 124
    assert c["b"] == 2


def test_per_entry_ttl():
    c, clk = mk(3, ttl=10)
    c.set("short", 1, ttl=1)
    c.set("long", 2, ttl=100)
    c.set("dflt", 3)
    clk.t = 101
    assert c.keys() == ["long", "dflt"]
    clk.t = 150
    assert c.keys() == ["long"]


def test_expired_do_not_count_toward_capacity():
    c, clk = mk(2, ttl=10)
    c["old"] = 0
    clk.t = 105
    c["x"] = 1
    clk.t = 111            # old expired, x live
    c["y"] = 2             # must not evict x
    assert c.keys() == ["x", "y"]
    assert len(c) == 2


def test_overwrite_never_evicts():
    c, _ = mk(2)
    c["a"] = 1; c["b"] = 2
    c["a"] = 10
    assert c.keys() == ["b", "a"]
    assert c.peek("a") == 10 and c.peek("b") == 2


def test_overwrite_of_expired_key_is_new_key():
    c, clk = mk(2, ttl=10)
    c["a"] = 1
    clk.t = 105
    c["b"] = 2
    clk.t = 111
    c["c"] = 3
    c["a"] = 9            # a was expired: counts as new, cache has b,c -> evict b
    assert c.keys() == ["c", "a"]


def test_delete_pop_clear():
    c, clk = mk(3, ttl=10)
    c["a"] = 1; c["b"] = 2
    del c["a"]
    assert "a" not in c
    with pytest.raises(KeyError):
        del c["a"]
    assert c.pop("b") == 2
    assert c.pop("b", "x") == "x"
    assert c.pop("b", None) is None
    with pytest.raises(KeyError):
        c.pop("b")
    c["e"] = 1
    clk.t = 200
    with pytest.raises(KeyError):
        del c["e"]
    with pytest.raises(KeyError):
        c.pop("e")
    c["f"] = 1; c["g"] = 2
    c.clear()
    assert len(c) == 0 and c.keys() == []


def test_falsy_values_and_none():
    c, _ = mk()
    c["z"] = 0; c["n"] = None
    assert c.get("z", 5) == 0
    assert "n" in c and c["n"] is None
    assert c.pop("n", "x") is None


def test_uses_injected_clock_only(monkeypatch):
    c, clk = mk(2, ttl=5)
    monkeypatch.setattr(time, "monotonic", lambda: 1e12)
    monkeypatch.setattr(time, "time", lambda: 1e12)
    c["a"] = 1
    assert c["a"] == 1


def test_default_clock_works():
    c = TTLLRUCache(2, 60)
    c["a"] = 1
    assert c["a"] == 1


def test_large_capacity_is_fast():
    c, clk = mk(1000, ttl=1000)
    t0 = time.perf_counter()
    for i in range(20000):
        c[i % 1400] = i
        c.get((i * 7) % 1400)
    assert time.perf_counter() - t0 < 10
    assert len(c) == 1000
