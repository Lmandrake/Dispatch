"""VersionedStore: the store of record.

In production this fronts a database; here it is an in-memory map from key to
the list of every Record ever written for that key. Reads return the newest
Record. Every write bumps the key's version and then notifies subscribers
(the caches use this to invalidate).

Read hooks
----------
``add_read_hook(fn)`` registers ``fn(key, record)`` to be called on every
``get`` after the record has been read and before it is returned (``record``
is None for a missing key). Hooks run outside the store's lock, in the
reading thread. They exist for tracing (the server's slow-read log), for
simulating backend latency, and for fault injection in tests: a hook that
raises makes the read fail with that exception.
"""

import threading
import time
from typing import Callable, Hashable, Iterator, List, Optional

from .clock import resolve
from .records import Record


class ConflictError(Exception):
    """compare_and_put saw a different version than expected."""


class VersionedStore:
    def __init__(self, clock=None, latency: float = 0.0):
        self._clock = resolve(clock)
        self._data: dict = {}
        self._lock = threading.RLock()
        self._listeners: List[Callable[[Record], None]] = []
        self._read_hooks: List[Callable] = []
        self._reads = 0
        self._writes = 0
        self.latency = float(latency)

    # ------------------------------------------------------------------ reads

    def get(self, key: Hashable) -> Optional[Record]:
        """Newest Record for ``key``, or None if it was never written.

        A deleted key returns its tombstone (``record.deleted`` is True).
        """
        with self._lock:
            self._reads += 1
            versions = self._data.get(key)
            record = versions[-1] if versions else None
            hooks = list(self._read_hooks)
        if self.latency:
            time.sleep(self.latency)
        for hook in hooks:
            hook(key, record)
        return record

    def version(self, key: Hashable) -> int:
        """Current version of ``key`` (0 if never written). Does not run hooks."""
        with self._lock:
            versions = self._data.get(key)
            return versions[-1].version if versions else 0

    def history(self, key: Hashable) -> List[Record]:
        with self._lock:
            return list(self._data.get(key, ()))

    def keys(self, kind: Optional[str] = None) -> Iterator[Hashable]:
        """Live (non-deleted) keys; with ``kind``, only tuple keys starting with it."""
        with self._lock:
            snapshot = [(k, v[-1]) for k, v in self._data.items()]
        for k, rec in snapshot:
            if rec.deleted:
                continue
            if kind is not None and not (isinstance(k, tuple) and k and k[0] == kind):
                continue
            yield k

    @property
    def reads(self) -> int:
        with self._lock:
            return self._reads

    @property
    def writes(self) -> int:
        with self._lock:
            return self._writes

    # ----------------------------------------------------------------- writes

    def put(self, key: Hashable, value) -> Record:
        """Write a new version of ``key`` and notify subscribers."""
        with self._lock:
            record = self._append(key, value, deleted=False)
        self._notify(record)
        return record

    def compare_and_put(self, key: Hashable, value, expected_version: int) -> Record:
        """Write only if the current version is ``expected_version``."""
        with self._lock:
            current = self.version(key)
            if current != expected_version:
                raise ConflictError(
                    f"{key!r}: expected version {expected_version}, found {current}"
                )
            record = self._append(key, value, deleted=False)
        self._notify(record)
        return record

    def delete(self, key: Hashable) -> Optional[Record]:
        """Write a tombstone. Returns it, or None if the key never existed."""
        with self._lock:
            if key not in self._data:
                return None
            record = self._append(key, None, deleted=True)
        self._notify(record)
        return record

    def _append(self, key, value, deleted) -> Record:
        versions = self._data.setdefault(key, [])
        version = versions[-1].version + 1 if versions else 1
        record = Record(key, value, version, self._clock(), deleted)
        versions.append(record)
        self._writes += 1
        return record

    # ------------------------------------------------------ hooks / listeners

    def subscribe(self, listener: Callable[[Record], None]) -> Callable[[], None]:
        """Call ``listener(record)`` after every write. Returns an unsubscribe function.

        Listeners run in the writing thread, after the store lock is released,
        in subscription order.
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe():
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def add_read_hook(self, hook: Callable) -> Callable[[], None]:
        """Register ``hook(key, record)``; see the module docstring. Returns a remover."""
        with self._lock:
            self._read_hooks.append(hook)

        def remove():
            with self._lock:
                if hook in self._read_hooks:
                    self._read_hooks.remove(hook)

        return remove

    def _notify(self, record: Record) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(record)
