"""Handler registry and the context a handler runs with.

A handler is a callable ``fn(ctx)`` registered for a job ``kind``. It returns
the job's result (any JSON value) or raises:

* :class:`taskmill.errors.PermanentError` fails the job immediately;
* :class:`taskmill.errors.Retry` retries after ``delay`` seconds (if given);
* any other exception retries with the queue's backoff policy.

``ctx`` is a :class:`JobContext`: the job's id, kind, queue, payload and
attempt number, plus ``heartbeat()`` (extend the lease now) and ``lost``
(true once the pool learned that the lease is gone; a well-behaved
long-running handler checks it and stops early, since its result will be
rejected anyway).
"""

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .errors import HandlerNotFound, PermanentError, ValidationError


class JobContext:
    def __init__(self, broker, reservation, worker: str):
        self.broker = broker
        self.reservation = reservation
        self.worker = worker
        self._lost = threading.Event()
        self._lost_reason: Optional[str] = None
        self.started = time.monotonic()

    # the job
    @property
    def job_id(self) -> str:
        return self.reservation.job_id

    @property
    def kind(self) -> str:
        return self.reservation.kind

    @property
    def queue(self) -> str:
        return self.reservation.queue

    @property
    def payload(self) -> Any:
        return self.reservation.payload

    @property
    def attempt(self) -> int:
        return self.reservation.attempt

    @property
    def token(self) -> str:
        return self.reservation.token

    # the lease
    def heartbeat(self, extend: Optional[float] = None) -> float:
        from .errors import LeaseLost
        try:
            return self.broker.heartbeat(self.token, extend)
        except LeaseLost as exc:
            self.mark_lost(str(exc))
            raise

    def mark_lost(self, reason: str) -> None:
        if not self._lost.is_set():
            self._lost_reason = reason
            self._lost.set()

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def lost_reason(self) -> Optional[str]:
        return self._lost_reason

    def wait_lost(self, timeout: float) -> bool:
        return self._lost.wait(timeout)

    def __repr__(self) -> str:
        return f"JobContext({self.job_id} attempt {self.attempt} on {self.worker})"


class Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: Dict[str, Callable] = {}

    def register(self, kind: str, fn: Callable = None):
        """``register("kind", fn)`` or ``@registry.register("kind")``."""
        from .job import validate_kind
        validate_kind(kind)

        def add(f):
            if not callable(f):
                raise ValidationError("handler must be callable")
            with self._lock:
                self._handlers[kind] = f
            return f

        return add(fn) if fn is not None else add

    def unregister(self, kind: str) -> bool:
        with self._lock:
            return self._handlers.pop(kind, None) is not None

    def get(self, kind: str) -> Callable:
        with self._lock:
            fn = self._handlers.get(kind)
        if fn is None:
            raise HandlerNotFound(f"no handler for kind {kind!r}")
        return fn

    def kinds(self) -> List[str]:
        with self._lock:
            return sorted(self._handlers)

    def __contains__(self, kind: str) -> bool:
        with self._lock:
            return kind in self._handlers


# --------------------------------------------------------------- built-ins

def _echo(ctx):
    return ctx.payload


def _sum(ctx):
    values = ctx.payload.get("values") if isinstance(ctx.payload, dict) else ctx.payload
    if not isinstance(values, list) or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for v in values):
        raise PermanentError("sum needs a list of numbers")
    return sum(values)


def _sleep(ctx):
    seconds = float((ctx.payload or {}).get("seconds", 0.1))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if ctx.wait_lost(min(0.05, max(0.0, end - time.monotonic()))):
            return None
    return {"slept": seconds}


def _fail(ctx):
    payload = ctx.payload or {}
    if payload.get("permanent"):
        raise PermanentError(payload.get("message", "failed on purpose"))
    until = payload.get("until_attempt")
    if until is not None and ctx.attempt >= until:
        return {"succeeded_on": ctx.attempt}
    raise RuntimeError(payload.get("message", "failed on purpose"))


BUILTINS = {"echo": _echo, "sum": _sum, "sleep": _sleep, "fail": _fail}


def default_registry() -> Registry:
    reg = Registry()
    for kind, fn in BUILTINS.items():
        reg.register(kind, fn)
    return reg
