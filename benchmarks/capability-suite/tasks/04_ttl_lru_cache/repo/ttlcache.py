"""A size-bounded LRU cache whose entries also expire after a time-to-live."""
import time
from typing import Any, Callable, Hashable, Optional

_MISSING = object()


class TTLLRUCache:
    """LRU cache with per-entry expiry.

    Constructor: ``TTLLRUCache(maxsize, ttl, clock=time.monotonic)``

    * ``maxsize`` (int >= 1) is the maximum number of live entries.
      Otherwise raise ValueError.
    * ``ttl`` (float > 0) is the default lifetime in seconds of an entry,
      measured from when it was last *set* (reads do not extend lifetime).
      Otherwise raise ValueError.
    * ``clock`` is a zero-argument callable returning the current time in
      seconds; tests inject a fake clock. Always use it, never call
      ``time`` directly.

    An entry set at time ``t`` with lifetime ``L`` is live while
    ``clock() < t + L`` and expired once ``clock() >= t + L``. Expired entries
    behave exactly as if absent from every method, and never count toward
    ``maxsize`` or ``len()``.

    Recency: ``set`` and a successful ``get`` (or ``cache[key]``) make the key
    the most recently used. ``in``, ``len``, ``peek`` and ``keys`` do not
    change recency.

    When a ``set`` of a new key would exceed ``maxsize`` live entries, expired
    entries are discarded first; if still full, the least recently used live
    entry is evicted. Overwriting an existing live key never evicts anything
    else.
    """

    def __init__(self, maxsize: int, ttl: float, clock: Callable[[], float] = time.monotonic):
        raise NotImplementedError

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """Store ``value``. ``ttl`` overrides the default lifetime for this entry
        (must be > 0, else ValueError)."""
        raise NotImplementedError

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the live value for ``key`` (marking it recently used), else ``default``."""
        raise NotImplementedError

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Like get, but does not affect recency."""
        raise NotImplementedError

    def __getitem__(self, key: Hashable) -> Any:
        """Like get, but raises KeyError if absent or expired."""
        raise NotImplementedError

    def __setitem__(self, key: Hashable, value: Any) -> None:
        """Same as ``set(key, value)``."""
        raise NotImplementedError

    def __delitem__(self, key: Hashable) -> None:
        """Remove ``key``; KeyError if absent or expired."""
        raise NotImplementedError

    def pop(self, key: Hashable, default: Any = _MISSING) -> Any:
        """Remove and return the live value; if absent/expired return ``default``,
        or raise KeyError when no default was given."""
        raise NotImplementedError

    def __contains__(self, key: Hashable) -> bool:
        raise NotImplementedError

    def __len__(self) -> int:
        """Number of live entries."""
        raise NotImplementedError

    def keys(self) -> list:
        """Live keys ordered from least to most recently used."""
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError
