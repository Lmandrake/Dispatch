"""Result cache: reuse the result of an identical, recently finished job.

Some job kinds are pure functions of their payload (renders, price sheets,
report exports). :class:`CachedSubmitter` sits in front of
``Broker.enqueue`` for such kinds: if an identical job finished
successfully within ``ttl`` seconds, its result is returned straight away
and nothing is enqueued; otherwise the job is enqueued as usual and its
result is cached when it completes. The rules are in docs/RESULT_CACHE.md.

The cache is in-memory and filled by :meth:`CachedSubmitter.collect`, which
is cheap and safe to call often (``install()`` calls it from the
``handler.end`` hook).
"""

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from . import codec
from .errors import ValidationError, UnknownJob
from .job import DONE, FINISHED, validate_tenant


@dataclass(frozen=True)
class Submitted:
    job_id: Optional[str]          # None for a cache hit
    cached: bool
    result: Any = None             # the cached result for a hit
    source_job: Optional[str] = None


class _Entry:
    __slots__ = ("result", "job_id", "stored_at")

    def __init__(self, result, job_id, stored_at):
        self.result = result
        self.job_id = job_id
        self.stored_at = stored_at


def fingerprint(queue: str, kind: str, payload: Any, tenant: Optional[str] = None) -> str:
    """The cache key for a job: a SHA-256 over its identifying fields."""
    codec.validate_json(payload, "payload")
    body = codec.encode({"q": queue, "k": kind, "p": payload})
    return hashlib.sha256(body).hexdigest()


class CachedSubmitter:
    def __init__(self, broker, kinds: Iterable[str], ttl: float = 300.0, maxsize: int = 10000):
        if ttl <= 0:
            raise ValidationError("ttl must be > 0")
        if maxsize < 1:
            raise ValidationError("maxsize must be >= 1")
        self.broker = broker
        self.kinds = frozenset(kinds)
        self.ttl = ttl
        self.maxsize = maxsize
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._pending: Dict[str, str] = {}          # job id -> fingerprint
        self._remove = None
        self.hits = 0
        self.misses = 0

    # ---------------------------------------------------------------- submit

    def submit(self, queue: str, kind: str, payload: Any = None, tenant: Optional[str] = None,
               **enqueue_kw) -> Submitted:
        tenant = validate_tenant(tenant)
        if kind not in self.kinds:
            res = self.broker.enqueue(queue, kind, payload, tenant=tenant, **enqueue_kw)
            return Submitted(res.job_id, False)
        fp = fingerprint(queue, kind, payload, tenant)
        now = self.broker.clock()
        with self._lock:
            e = self._entries.get(fp)
            if e is not None and now - e.stored_at < self.ttl:
                self._entries.move_to_end(fp)
                self.hits += 1
                hit = Submitted(None, True, codec.copy_json(e.result), e.job_id)
            else:
                if e is not None:
                    del self._entries[fp]
                self.misses += 1
                hit = None
        if hit is not None:
            self.broker.metrics.inc("resultcache.hits", kind=kind)
            return hit
        self.broker.metrics.inc("resultcache.misses", kind=kind)
        res = self.broker.enqueue(queue, kind, payload, tenant=tenant, **enqueue_kw)
        with self._lock:
            self._pending[res.job_id] = fp
        return Submitted(res.job_id, False)

    # --------------------------------------------------------------- collect

    def collect(self) -> int:
        """Move results of finished pending jobs into the cache. Returns how many were stored."""
        with self._lock:
            pending = list(self._pending.items())
        stored = 0
        for job_id, fp in pending:
            try:
                job = self.broker.get(job_id)
            except UnknownJob:
                with self._lock:
                    self._pending.pop(job_id, None)
                continue
            if job.state not in FINISHED:
                continue
            with self._lock:
                self._pending.pop(job_id, None)
                if job.state == DONE:
                    self._store(fp, job.result, job_id, job.finished_at)
                    stored += 1
        return stored

    def _store(self, fp: str, result, job_id: str, at: float) -> None:
        self._entries[fp] = _Entry(codec.copy_json(result), job_id, at)
        self._entries.move_to_end(fp)
        while len(self._entries) > self.maxsize:
            self._entries.popitem(last=False)

    # ------------------------------------------------------------ management

    def install(self) -> "CachedSubmitter":
        if self._remove is None:
            self._remove = self.broker.hooks.add("handler.end", lambda **kw: self.collect())
        return self

    def uninstall(self) -> None:
        if self._remove is not None:
            self._remove()
            self._remove = None

    def invalidate(self, queue: str, kind: str, payload: Any, tenant: Optional[str] = None) -> bool:
        fp = fingerprint(queue, kind, payload, tenant)
        with self._lock:
            return self._entries.pop(fp, None) is not None

    def clear(self) -> int:
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"entries": len(self._entries), "pending": len(self._pending), "hits": self.hits,
                    "misses": self.misses}

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
