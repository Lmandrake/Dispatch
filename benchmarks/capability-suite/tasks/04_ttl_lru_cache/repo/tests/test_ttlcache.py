from ttlcache import TTLLRUCache


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_basic_set_get():
    c = TTLLRUCache(2, 10, clock=Clock())
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None
