"""ReadThroughCache: a TTL + LRU memoizing cache in front of a loader.

``get(key, loader)`` returns the cached value for ``key`` if it is present and
fresh; otherwise it calls ``loader(key)``, caches the result and returns it.
Loaders are slow (they hit the store), so they run WITHOUT the cache lock
held: loads for different keys proceed in parallel, and a writer invalidating
an entry never waits for a load to finish.

Expiry
------
An entry stored at time ``t`` is fresh while ``clock() < t + ttl`` and expired
from ``t + ttl`` on (so ttl=0 caches nothing). Expired entries are dropped
lazily when touched, or by ``purge_expired()``. ``ttl=None`` means entries
never expire.

Eviction
--------
At most ``maxsize`` entries are kept; storing a new key into a full cache
evicts the least recently used entry (a hit counts as a use). Expired entries
are purged before choosing a victim, so they never push out a fresh entry.

Invalidation
------------
``invalidate(key)`` drops one entry, ``invalidate_where(pred)`` every entry
whose key satisfies ``pred``, ``clear()`` everything. After an invalidation
returns, no ``get`` may return a value computed from data older than the
invalidation.

Stats
-----
Counters ``<name>.hits``, ``<name>.misses``, ``<name>.loads``,
``<name>.load_errors``, ``<name>.evictions``, ``<name>.expired`` and
``<name>.invalidations`` (entries actually removed) are kept in ``stats``.
A loader that raises is counted in ``load_errors``; nothing is cached and the
exception propagates to the caller.
"""

import threading
from collections import OrderedDict
from typing import Callable, Hashable, Optional

from .clock import resolve
from .stats import Stats

_MISSING = object()


class _Entry:
    __slots__ = ("value", "stored_at", "expires_at")

    def __init__(self, value, stored_at, expires_at):
        self.value = value
        self.stored_at = stored_at
        self.expires_at = expires_at


class ReadThroughCache:
    def __init__(
        self,
        name: str,
        ttl: Optional[float] = 60.0,
        maxsize: int = 1024,
        clock=None,
        stats: Optional[Stats] = None,
    ):
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        if ttl is not None and ttl < 0:
            raise ValueError("ttl must be >= 0 or None")
        self.name = name
        self.ttl = ttl
        self.maxsize = maxsize
        self._clock = resolve(clock)
        self.stats = stats if stats is not None else Stats(clock=self._clock)
        self._entries: "OrderedDict[Hashable, _Entry]" = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------- internals

    def _count(self, what: str, n: int = 1) -> None:
        if n:
            self.stats.incr(f"{self.name}.{what}", n)

    def _expires_at(self, now: float) -> float:
        return float("inf") if self.ttl is None else now + self.ttl

    def _lookup(self, key, now):
        """Fresh value for key or _MISSING. Caller holds the lock."""
        entry = self._entries.get(key)
        if entry is None:
            return _MISSING
        if now >= entry.expires_at:
            del self._entries[key]
            self._count("expired")
            return _MISSING
        self._entries.move_to_end(key)
        return entry.value

    def _purge_expired_locked(self, now) -> int:
        dead = [k for k, e in self._entries.items() if now >= e.expires_at]
        for k in dead:
            del self._entries[k]
        self._count("expired", len(dead))
        return len(dead)

    def _store(self, key, value, now) -> None:
        """Insert or replace key. Caller holds the lock."""
        if self.ttl == 0:
            return
        if key in self._entries:
            self._entries.move_to_end(key)
        elif len(self._entries) >= self.maxsize:
            self._purge_expired_locked(now)
            while len(self._entries) >= self.maxsize:
                self._entries.popitem(last=False)
                self._count("evictions")
        self._entries[key] = _Entry(value, now, self._expires_at(now))

    # ------------------------------------------------------------------- API

    def get(self, key: Hashable, loader: Callable[[Hashable], object]):
        now = self._clock()
        with self._lock:
            value = self._lookup(key, now)
        if value is not _MISSING:
            self._count("hits")
            return value

        self._count("misses")
        try:
            value = loader(key)
        except Exception:
            self._count("load_errors")
            raise
        self._count("loads")

        now = self._clock()
        with self._lock:
            self._store(key, value, now)
        return value

    def peek(self, key: Hashable, default=None):
        """The cached value if present and fresh, without loading or touching LRU order."""
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or now >= entry.expires_at:
                return default
            return entry.value

    def put(self, key: Hashable, value) -> None:
        """Store ``value`` directly (used for warming)."""
        now = self._clock()
        with self._lock:
            self._store(key, value, now)

    def invalidate(self, key: Hashable) -> bool:
        with self._lock:
            removed = self._entries.pop(key, None) is not None
        if removed:
            self._count("invalidations")
        return removed

    def invalidate_where(self, pred: Callable[[Hashable], bool]) -> int:
        with self._lock:
            doomed = [k for k in self._entries if pred(k)]
            for k in doomed:
                del self._entries[k]
        self._count("invalidations", len(doomed))
        return len(doomed)

    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
        self._count("invalidations", n)
        return n

    def purge_expired(self) -> int:
        now = self._clock()
        with self._lock:
            return self._purge_expired_locked(now)

    def keys(self):
        """Keys currently held (fresh or not), least recently used first."""
        with self._lock:
            return list(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, key) -> bool:
        return self.peek(key, _MISSING) is not _MISSING

    def __repr__(self) -> str:
        return f"ReadThroughCache({self.name!r}, ttl={self.ttl}, size={len(self)}/{self.maxsize})"
