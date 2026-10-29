"""Named in-process mutexes with lease semantics.

Handlers that must not run concurrently on one resource (a customer account,
a file, an upstream API) take a mutex by name. Unlike ``threading.Lock`` a
:class:`MutexManager` lock is a *lease*: it carries an owner, a token and a
time-to-live measured on the manager's clock. A holder that crashes or hangs
loses the mutex when the lease expires, so a stuck handler cannot block the
resource forever; the former holder's ``release`` and ``renew`` then fail
because its token no longer matches.

``acquire`` returns a :class:`MutexLease` or ``None``. With ``timeout`` it
waits (in real time, woken by releases) for the mutex; expiry is evaluated on
the manager's clock each time it wakes, so a ``ManualClock`` test can expire a
lease by advancing the clock and then calling ``acquire`` again.

Job integration: :func:`ctx_lock` is a context manager that locks on behalf
of a handler's ``JobContext`` (the job id is the owner) and renews the lease
alongside ``ctx.heartbeat``; :func:`exclusive` wraps a handler so that it
runs only while it holds the mutex, and asks the broker to retry the job
later (via :class:`taskmill.errors.Retry`) when the mutex is busy.
"""

import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional

from .clock import resolve
from .errors import Retry, TaskmillError


class MutexBusy(TaskmillError):
    """The mutex is held by someone else and the wait ran out."""
    status = 409


class MutexLost(TaskmillError):
    """The caller's lease is no longer the current one (expired or released)."""
    status = 409


@dataclass(frozen=True)
class MutexLease:
    name: str
    owner: str
    token: str
    acquired_at: float
    expires_at: float

    def remaining(self, now: float) -> float:
        return self.expires_at - now


@dataclass
class MutexStats:
    acquired: int = 0
    contended: int = 0
    expired: int = 0
    released: int = 0
    renewed: int = 0
    wait_seconds: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class MutexManager:
    def __init__(self, clock=None, default_ttl: float = 30.0):
        if not default_ttl > 0:
            raise ValueError("default_ttl must be > 0")
        self.clock = resolve(clock)
        self.default_ttl = default_ttl
        self._cond = threading.Condition()
        self._held: Dict[str, MutexLease] = {}
        self._stats: Dict[str, MutexStats] = {}

    def _stat(self, name: str) -> MutexStats:
        return self._stats.setdefault(name, MutexStats())

    def _expire_locked(self, name: str, now: float) -> None:
        lease = self._held.get(name)
        if lease is not None and lease.expires_at <= now:
            del self._held[name]
            self._stat(name).expired += 1

    def try_acquire(self, name: str, owner: str, ttl: Optional[float] = None) -> Optional[MutexLease]:
        ttl = self.default_ttl if ttl is None else ttl
        if not ttl > 0:
            raise ValueError("ttl must be > 0")
        with self._cond:
            now = self.clock()
            self._expire_locked(name, now)
            if name in self._held:
                self._stat(name).contended += 1
                return None
            lease = MutexLease(name, owner, secrets.token_hex(8), now, now + ttl)
            self._held[name] = lease
            self._stat(name).acquired += 1
            return lease

    def acquire(self, name: str, owner: str, ttl: Optional[float] = None,
                timeout: float = 0.0) -> Optional[MutexLease]:
        started = time.monotonic()
        while True:
            lease = self.try_acquire(name, owner, ttl)
            if lease is not None:
                self._add_wait(name, time.monotonic() - started)
                return lease
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                self._add_wait(name, time.monotonic() - started)
                return None
            with self._cond:
                self._cond.wait(min(remaining, 0.05))

    def _add_wait(self, name: str, seconds: float) -> None:
        with self._cond:
            self._stat(name).wait_seconds += seconds

    def renew(self, lease: MutexLease, ttl: Optional[float] = None) -> MutexLease:
        ttl = self.default_ttl if ttl is None else ttl
        with self._cond:
            now = self.clock()
            self._expire_locked(lease.name, now)
            current = self._held.get(lease.name)
            if current is None or current.token != lease.token:
                raise MutexLost(f"mutex {lease.name!r} is no longer held by {lease.owner}")
            renewed = MutexLease(lease.name, lease.owner, lease.token, lease.acquired_at, now + ttl)
            self._held[lease.name] = renewed
            self._stat(lease.name).renewed += 1
            return renewed

    def release(self, lease: MutexLease) -> bool:
        """Release a lease. False when it had already expired or been replaced."""
        with self._cond:
            self._expire_locked(lease.name, self.clock())
            current = self._held.get(lease.name)
            if current is None or current.token != lease.token:
                return False
            del self._held[lease.name]
            self._stat(lease.name).released += 1
            self._cond.notify_all()
            return True

    def holder(self, name: str) -> Optional[MutexLease]:
        with self._cond:
            self._expire_locked(name, self.clock())
            return self._held.get(name)

    def locked(self, name: str) -> bool:
        return self.holder(name) is not None

    def held(self) -> List[MutexLease]:
        with self._cond:
            now = self.clock()
            for name in list(self._held):
                self._expire_locked(name, now)
            return sorted(self._held.values(), key=lambda l: l.name)

    def stats(self) -> Dict[str, dict]:
        with self._cond:
            return {name: st.to_dict() for name, st in sorted(self._stats.items())}

    @contextmanager
    def hold(self, name: str, owner: str, ttl: Optional[float] = None, timeout: float = 0.0) -> Iterator[MutexLease]:
        lease = self.acquire(name, owner, ttl, timeout)
        if lease is None:
            raise MutexBusy(f"mutex {name!r} is held by {self.holder(name).owner if self.holder(name) else '?'}")
        try:
            yield lease
        finally:
            self.release(lease)


class _CtxLease:
    """A held mutex bound to a job context: ``heartbeat`` renews both lease and mutex."""

    def __init__(self, manager: MutexManager, ctx, lease: MutexLease, ttl: Optional[float]):
        self.manager = manager
        self.ctx = ctx
        self.lease = lease
        self.ttl = ttl

    def heartbeat(self) -> None:
        self.lease = self.manager.renew(self.lease, self.ttl)
        self.ctx.heartbeat()


@contextmanager
def ctx_lock(manager: MutexManager, ctx, name: str, ttl: Optional[float] = None,
             timeout: float = 0.0) -> Iterator[_CtxLease]:
    with manager.hold(name, ctx.job_id, ttl, timeout) as lease:
        yield _CtxLease(manager, ctx, lease, ttl)


def exclusive(manager: MutexManager, name: Callable, ttl: Optional[float] = None,
              retry_in: float = 5.0) -> Callable:
    """Decorator for a handler. ``name`` maps the ``ctx`` to the mutex name (or is a plain string)."""

    def wrap(handler: Callable) -> Callable:
        def run(ctx):
            key = name(ctx) if callable(name) else name
            lease = manager.try_acquire(key, ctx.job_id, ttl)
            if lease is None:
                raise Retry(retry_in, f"mutex {key!r} is busy")
            try:
                return handler(ctx)
            finally:
                manager.release(lease)

        run.__name__ = getattr(handler, "__name__", "exclusive_handler")
        return run

    return wrap
