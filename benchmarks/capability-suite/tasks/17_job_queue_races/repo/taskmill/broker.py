"""The Broker: queues, leases, retries and durability in one object.

The concurrency model is described in docs/DESIGN.md, leases in
docs/LEASES.md and retries in docs/RETRIES.md.
"""

import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from . import codec
from .backoff import parse_backoff
from .clock import resolve
from .config import BrokerConfig, check_queue_name
from .errors import (BrokerClosed, InvalidTransition, LeaseLost, ResultTooLarge, UnknownJob,
                     ValidationError)
from .events import Hooks
from .idempotency import normalize_key
from .ids import format_job_id, job_id_sort_key, new_token
from .job import (CANCELLED, DELAYED, DONE, FAILED, FINISHED, PENDING, RESERVED, Job,
                  validate_kind, validate_priority, validate_tags, validate_tenant)
from .metrics import Metrics
from .pqueue import best_of
from .ratelimit import RateLimits
from .results import ResultView, Waiters, WorkSignal
from .state import State

MAX_ERROR_CHARS = 2000


@dataclass(frozen=True)
class Enqueued:
    job_id: str
    created: bool          # False when an idempotency key matched an existing job

    def __str__(self) -> str:
        return self.job_id


@dataclass(frozen=True)
class Reservation:
    job_id: str
    token: str
    queue: str
    kind: str
    payload: Any
    attempt: int
    max_attempts: int
    deadline: float
    priority: int
    tenant: Optional[str] = None

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "token": self.token, "queue": self.queue, "kind": self.kind,
                "payload": self.payload, "attempt": self.attempt, "max_attempts": self.max_attempts,
                "deadline": self.deadline, "priority": self.priority, "tenant": self.tenant}


def clean_error(error) -> str:
    """One-line-ish error text, at most MAX_ERROR_CHARS characters."""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    else:
        text = "" if error is None else str(error)
    text = text.replace("\r\n", "\n").strip()
    if len(text) > MAX_ERROR_CHARS:
        text = text[: MAX_ERROR_CHARS - 3] + "..."
    return text


class Broker:
    def __init__(self, data_dir: Optional[str] = None, config: Optional[BrokerConfig] = None,
                 clock=None, hooks: Optional[Hooks] = None, metrics: Optional[Metrics] = None):
        self.config = (config or BrokerConfig()).validate()
        self.clock = resolve(clock)
        self.hooks = hooks if hooks is not None else Hooks()
        self.metrics = metrics if metrics is not None else Metrics(clock=self.clock)
        self.data_dir = data_dir
        self.state = State(self.config)
        self._lock = threading.RLock()
        self._waiters = Waiters(self._lock)
        self._signal = WorkSignal()
        self._ratelimits = RateLimits()
        self._seq = 0
        self._closed = False
        self._wal = None
        self._since_checkpoint = 0
        self._checkpointing = threading.Lock()
        self.recovery = None
        self._open()

    # ================================================================ lifecycle

    def _open(self) -> None:
        now = self.clock()
        for name, qc in self.config.queues.items():
            self.state.queue(name)
            if qc.paused:
                self.state.paused.add(name)
            if qc.rate is not None:
                self._ratelimits.configure(name, qc.rate, qc.burst, now)
        if self.data_dir is None:
            return
        from . import recovery
        from .wal import WriteAheadLog
        self._wal = WriteAheadLog(recovery.wal_dir(self.data_dir), fsync=self.config.wal_fsync,
                                  segment_bytes=self.config.wal_segment_bytes, hooks=self.hooks)
        scan = self._wal.open()
        self.recovery = recovery.recover(self.state, self.data_dir, scan)
        self._seq = self.recovery.last_seq

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._waiters.notify_all()
        self._signal.pulse()
        if self._wal is not None:
            self._wal.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _check_open(self) -> None:
        if self._closed:
            raise BrokerClosed("broker is closed")

    # ================================================================ plumbing

    def _commit_locked(self, out: List[dict], op: str, **fields) -> dict:
        """Create, number and apply one record. Caller holds the lock."""
        self._seq += 1
        rec = {"seq": self._seq, "op": op}
        rec.update(fields)
        finished = self.state.apply(rec)
        out.append(rec)
        if finished:
            self._waiters.notify(finished)
        return rec

    def _log(self, records: List[dict]) -> None:
        """Make ``records`` durable. Caller must NOT hold the lock."""
        if not records:
            return
        if self._wal is not None:
            self._wal.append(records)
            self.metrics.inc("wal.records", len(records))
            self._since_checkpoint += len(records)
        every = self.config.checkpoint_every
        if self._wal is not None and every and self._since_checkpoint >= every:
            if self._checkpointing.acquire(blocking=False):
                try:
                    self._checkpoint()
                finally:
                    self._checkpointing.release()

    @staticmethod
    def _copy(job: Job) -> Job:
        j = Job.from_dict(job.to_dict())
        j.payload = codec.copy_json(job.payload)
        j.result = codec.copy_json(job.result)
        return j

    def _job_locked(self, job_id: str) -> Job:
        job = self.state.jobs.get(job_id)
        if job is None:
            raise UnknownJob(f"no job {job_id}")
        return job

    def _lost(self, op: str, exc: LeaseLost) -> LeaseLost:
        self.metrics.inc("leases.lost", op=op)
        return exc

    # ================================================================ enqueue

    def enqueue(self, queue: str, kind: str, payload: Any = None, *, priority: Optional[int] = None,
                delay: Optional[float] = None, run_at: Optional[float] = None,
                idempotency_key: Optional[str] = None, max_attempts: Optional[int] = None,
                tags: Optional[Iterable[str]] = None, backoff: Optional[dict] = None,
                tenant: Optional[str] = None) -> Enqueued:
        """Add a job. With ``idempotency_key``, a key already held on ``queue`` returns that job."""
        check_queue_name(queue)
        validate_kind(kind)
        codec.check_size(payload, self.config.max_payload_bytes, "payload")
        payload = codec.roundtrip(payload)
        priority = self.config.default_priority if priority is None else validate_priority(priority)
        tags = validate_tags(tags)
        tenant = validate_tenant(tenant)
        if delay is not None and run_at is not None:
            raise ValidationError("give delay or run_at, not both")
        if delay is not None and not (delay >= 0):
            raise ValidationError("delay must be >= 0")
        if max_attempts is not None and (isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
                                         or max_attempts < 1):
            raise ValidationError("max_attempts must be a positive integer")
        if backoff is not None:
            backoff = parse_backoff(backoff).to_dict()
        key = normalize_key(idempotency_key) if idempotency_key is not None else None

        out: List[dict] = []
        with self._lock:
            self._check_open()
            now = self.clock()
            if key is not None:
                existing = self.state.idem.lookup(queue, key, now)
                if existing is not None and existing in self.state.jobs:
                    self.metrics.inc("jobs.deduplicated", queue=queue)
                    return Enqueued(existing, False)
            when = now if run_at is None and delay is None else (run_at if run_at is not None else now + delay)
            n = self.state.next_id
            job = Job(
                id=format_job_id(self.config.id_prefix, n),
                queue=queue,
                kind=kind,
                payload=payload,
                priority=priority,
                state=PENDING if when <= now else DELAYED,
                seq=self._seq + 1,
                enqueued_at=now,
                run_at=when,
                ready_at=max(when, now),
                max_attempts=max_attempts or self.config.max_attempts_for(queue),
                idempotency_key=key,
                tags=tags,
                backoff=backoff,
                tenant=tenant,
            )
            self._commit_locked(out, "enqueue", job=job.to_dict())
            snapshot = self._copy(self.state.jobs[job.id])
        self._log(out)
        self.metrics.inc("jobs.enqueued", queue=queue)
        self._signal.pulse()
        self.hooks.fire("enqueue", job=snapshot)
        return Enqueued(job.id, True)

    # ================================================================ reserve

    def _expire_locked(self, now: float, out: List[dict]) -> List[str]:
        expired = []
        for lease in self.state.leases.expired(now):
            job = self.state.jobs.get(lease.job_id)
            if job is None or job.state != RESERVED or job.lease_token != lease.token:
                continue
            to = FAILED if job.attempts_left < 0 else PENDING
            self._commit_locked(out, "expire", id=job.id, token=lease.token, at=now, to=to)
            self.metrics.inc("jobs.expired", queue=job.queue)
            if to == FAILED:
                self.metrics.inc("jobs.failed", queue=job.queue)
            expired.append(job.id)
        return expired

    def reserve(self, worker: Optional[str] = None, queues: Optional[Iterable[str]] = None,
                timeout: float = 0.0) -> Optional[Reservation]:
        """Lease the most urgent ready job, waiting up to ``timeout`` seconds for one."""
        wanted = None if queues is None else set(queues)
        deadline_wait = None
        while True:
            seen = self._signal.generation
            res, expired = self._try_reserve(worker, wanted)
            if expired:
                self.hooks.fire("reap", expired=expired)
            if res is not None:
                self.hooks.fire("reserve", job_id=res.job_id, token=res.token, worker=worker)
                return res
            if timeout <= 0:
                return None
            import time as _time
            if deadline_wait is None:
                deadline_wait = _time.monotonic() + timeout
            remaining = deadline_wait - _time.monotonic()
            if remaining <= 0 or self._closed:
                return None
            # Delayed jobs and expiring leases are driven by the broker clock,
            # which need not be real time: poll at least every 50 ms.
            self._signal.wait(min(remaining, 0.05), seen)

    def _try_reserve(self, worker, wanted):
        out: List[dict] = []
        res = None
        with self._lock:
            self._check_open()
            now = self.clock()
            expired = self._expire_locked(now, out)
            candidates = [q for name, q in self.state.queues.items()
                          if (wanted is None or name in wanted)
                          and name not in self.state.paused
                          and self._ratelimits.allows(name, now)]
            pick = best_of(candidates, now)
            if pick is not None:
                q, job = pick
                self._ratelimits.take(q.name, now)
                token = new_token()
                deadline = now + self.config.visibility_timeout_for(job.queue)
                self._commit_locked(out, "reserve", id=job.id, token=token, worker=worker, at=now,
                                    deadline=deadline)
                res = Reservation(job.id, token, job.queue, job.kind, codec.copy_json(job.payload),
                                  job.attempts, job.max_attempts, deadline, job.priority, job.tenant)
                self.metrics.inc("jobs.reserved", queue=job.queue)
        self._log(out)
        if expired:
            self._signal.pulse()
        return res, expired

    # ================================================================ finish

    def ack(self, token: str, result: Any = None) -> None:
        """Complete the delivery held under ``token`` with ``result``."""
        with self._lock:
            self._check_open()
            try:
                lease = self.state.leases.resolve(token, self.clock())
            except LeaseLost as exc:
                raise self._lost("ack", exc)
            job_id = lease.job_id
        codec.check_size(result, self.config.max_result_bytes, "result", ResultTooLarge)
        result = codec.roundtrip(result)
        self.hooks.fire("ack.before_commit", job_id=job_id, token=token)

        out: List[dict] = []
        with self._lock:
            self._check_open()
            now = self.clock()
            job = self._job_locked(job_id)
            self._commit_locked(out, "ack", id=job_id, token=token, result=result, at=now)
            queue = job.queue
        self._log(out)
        self.metrics.inc("jobs.acked", queue=queue)

    def nack(self, token: str, error: Any = "", retry_in: Optional[float] = None,
             permanent: bool = False) -> str:
        """Fail the delivery held under ``token``. Returns the job's new state."""
        if retry_in is not None and not (retry_in >= 0):
            raise ValidationError("retry_in must be >= 0")
        with self._lock:
            self._check_open()
            try:
                lease = self.state.leases.resolve(token, self.clock())
            except LeaseLost as exc:
                raise self._lost("nack", exc)
            job_id = lease.job_id
        message = clean_error(error)
        self.hooks.fire("nack.before_commit", job_id=job_id, token=token)

        out: List[dict] = []
        with self._lock:
            self._check_open()
            now = self.clock()
            job = self._job_locked(job_id)
            if permanent or job.attempts >= job.max_attempts:
                self._commit_locked(out, "fail", id=job_id, token=token, error=message, at=now)
                new_state = FAILED
                self.metrics.inc("jobs.failed", queue=job.queue)
            else:
                if retry_in is None:
                    spec = job.backoff or self.config.backoff_for(job.queue)
                    retry_in = parse_backoff(spec).delay(job.attempts, job.id)
                self._commit_locked(out, "retry", id=job_id, token=token, run_at=now + retry_in,
                                    error=message, at=now)
                new_state = DELAYED
                self.metrics.inc("jobs.retried", queue=job.queue)
        self._log(out)
        self._signal.pulse()
        return new_state

    def release(self, token: str) -> None:
        """Give back a delivery that was never started: pending again, the attempt not counted."""
        out: List[dict] = []
        with self._lock:
            self._check_open()
            try:
                lease = self.state.leases.resolve(token, self.clock())
            except LeaseLost as exc:
                raise self._lost("release", exc)
            self._commit_locked(out, "release", id=lease.job_id, token=token, at=self.clock())
        self._log(out)
        self._signal.pulse()

    def heartbeat(self, token: str, extend: Optional[float] = None) -> float:
        """Extend the lease held under ``token``. Returns the new deadline."""
        if extend is not None and not (extend > 0):
            raise ValidationError("extend must be > 0")
        out: List[dict] = []
        with self._lock:
            self._check_open()
            now = self.clock()
            try:
                job_id = self.state.leases._by_token.get(token)
                job = self.state.jobs.get(job_id) if job_id else None
                vt = self.config.visibility_timeout_for(job.queue) if job else self.config.visibility_timeout
                lease, deadline = self.state.leases.renewal(
                    token, now, extend if extend is not None else vt, self.config.max_visibility_timeout)
            except LeaseLost as exc:
                raise self._lost("heartbeat", exc)
            self._commit_locked(out, "heartbeat", id=lease.job_id, token=lease.token, deadline=deadline)
        self._log(out)
        self.metrics.inc("leases.heartbeats")
        self.hooks.fire("heartbeat", job_id=lease.job_id, token=token, deadline=deadline)
        return deadline

    # ================================================================ operator

    def cancel(self, job_id: str) -> bool:
        """Cancel a waiting or reserved job. False if it had already finished."""
        with self._lock:
            self._check_open()
            job = self._job_locked(job_id)
            if job.state in FINISHED:
                return False
            state = job.state
        self.hooks.fire("cancel.before_commit", job_id=job_id, state=state)
        out: List[dict] = []
        with self._lock:
            self._check_open()
            job = self._job_locked(job_id)
            self._commit_locked(out, "cancel", id=job_id, at=self.clock(), **{"from": state})
            queue = job.queue
        self._log(out)
        self.metrics.inc("jobs.cancelled", queue=queue)
        return True

    def retry(self, job_id: str) -> None:
        """Operator retry: put a failed or cancelled job back to pending with fresh attempts."""
        out: List[dict] = []
        with self._lock:
            self._check_open()
            job = self._job_locked(job_id)
            if job.state not in (FAILED, CANCELLED):
                raise InvalidTransition(f"{job_id}: only failed or cancelled jobs can be retried (is {job.state})")
            self._commit_locked(out, "requeue", id=job_id, at=self.clock())
        self._log(out)
        self._signal.pulse()

    def set_priority(self, job_id: str, priority: int) -> None:
        validate_priority(priority)
        out: List[dict] = []
        with self._lock:
            self._check_open()
            job = self._job_locked(job_id)
            if job.state in FINISHED:
                raise InvalidTransition(f"{job_id}: cannot reprioritise a {job.state} job")
            self._commit_locked(out, "priority", id=job_id, priority=priority)
        self._log(out)

    def pause(self, queue: str) -> None:
        self._set_paused(queue, True)

    def resume(self, queue: str) -> None:
        self._set_paused(queue, False)
        self._signal.pulse()

    def _set_paused(self, queue: str, paused: bool) -> None:
        check_queue_name(queue)
        out: List[dict] = []
        with self._lock:
            self._check_open()
            if (queue in self.state.paused) == paused and queue in self.state.queues:
                return
            self._commit_locked(out, "pause", queue=queue, paused=paused)
        self._log(out)

    def reap(self) -> List[str]:
        """Expire every lease whose deadline has passed. Returns the affected job ids."""
        out: List[dict] = []
        with self._lock:
            self._check_open()
            expired = self._expire_locked(self.clock(), out)
        self._log(out)
        if expired:
            self._signal.pulse()
            self.hooks.fire("reap", expired=expired)
        return expired

    def purge(self) -> List[str]:
        """Drop finished jobs older than ``retention``; forget expired keys and tokens."""
        out: List[dict] = []
        with self._lock:
            self._check_open()
            now = self.clock()
            cutoff = now - self.config.retention
            ids = sorted((j.id for j in self.state.jobs.values()
                          if j.state in FINISHED and j.finished_at is not None and j.finished_at <= cutoff),
                         key=job_id_sort_key)
            if ids:
                self._commit_locked(out, "purge", ids=ids)
            self.state.idem.prune(now)
            self.state.leases.prune_retired(now)
            for q in self.state.queues.values():
                q.compact()
        self._log(out)
        if ids:
            self.metrics.inc("jobs.purged", len(ids))
        return ids

    # ================================================================ checkpoint

    def checkpoint(self) -> Optional[str]:
        """Write a snapshot and drop the WAL segments it covers. Returns its path."""
        if self._wal is None:
            return None
        with self._checkpointing:
            return self._checkpoint()

    def _checkpoint(self) -> str:
        from . import recovery
        from . import snapshot as snapmod
        with self._lock:
            self._check_open()
            jobs = self.state.export_jobs()
            queues = self.state.export_queues()
            next_id = self.state.next_id
            self._since_checkpoint = 0
        self.hooks.fire("checkpoint.begin", jobs=len(jobs))
        self._wal.rotate()
        snap = snapmod.Snapshot(last_seq=self.last_seq, next_id=next_id, jobs=jobs, queues=queues,
                                created_at=self.clock())
        path = snapmod.write_snapshot(recovery.snapshot_dir(self.data_dir), snap)
        self._wal.drop_through(snap.last_seq)
        snapmod.prune_snapshots(recovery.snapshot_dir(self.data_dir), self.config.snapshots_kept)
        self.metrics.inc("checkpoints")
        self.hooks.fire("checkpoint", last_seq=snap.last_seq)
        return path

    # ================================================================ queries

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._copy(self._job_locked(job_id))

    def result(self, job_id: str) -> ResultView:
        with self._lock:
            return self._view(self._job_locked(job_id))

    @staticmethod
    def _view(job: Job) -> ResultView:
        return ResultView(job.id, job.state, codec.copy_json(job.result) if job.state == DONE else None,
                          job.last_error if job.state in (FAILED, CANCELLED) else None,
                          job.attempts, job.finished_at)

    def wait(self, job_id: str, timeout: Optional[float] = None) -> Optional[ResultView]:
        """Block until the job is finished (or the broker closes). None on timeout."""
        with self._lock:
            job = self._job_locked(job_id)

            def done():
                j = self.state.jobs.get(job_id)
                return self._closed or j is None or j.state in FINISHED

            if not self._waiters.wait_until(job_id, done, timeout):
                return None
            j = self.state.jobs.get(job_id)
            return None if j is None or j.state not in FINISHED else self._view(j)

    def jobs(self, queue: Optional[str] = None, state: Optional[str] = None) -> List[Job]:
        with self._lock:
            return [self._copy(j) for j in self.state.find(queue, state)]

    def queue_names(self) -> List[str]:
        with self._lock:
            return sorted(self.state.queues)

    def queue_stats(self, queue: str) -> Dict[str, Any]:
        with self._lock:
            if queue not in self.state.queues:
                raise UnknownJob(f"no queue {queue}")
            c = self.state.counts(queue)
            c["paused"] = queue in self.state.paused
            c["rate_limited"] = self._ratelimits.limited(queue)
            return c

    def order(self, queue: str) -> List[str]:
        """Job ids of ``queue`` in the order they would be reserved now."""
        with self._lock:
            q = self.state.queues.get(queue)
            return [] if q is None else [j.id for j in q.ordered(self.clock())]

    def leases(self) -> List[dict]:
        with self._lock:
            return [l.to_dict() for l in self.state.leases.active()]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            totals = {s: 0 for s in (PENDING, DELAYED, RESERVED, DONE, FAILED, CANCELLED)}
            for j in self.state.jobs.values():
                totals[j.state] += 1
            return {
                "jobs": len(self.state.jobs),
                "states": totals,
                "queues": sorted(self.state.queues),
                "paused": sorted(self.state.paused),
                "leases": len(self.state.leases),
                "idempotency_keys": len(self.state.idem),
                "last_seq": self._seq,
                "next_id": self.state.next_id,
            }

    def fingerprint(self) -> List[dict]:
        """Every job as a plain dict (delayed jobs that are due count as pending).

        Two brokers that went through the same operations, or a broker and
        its recovered copy, have equal fingerprints at the same clock time.
        """
        with self._lock:
            now = self.clock()
            for q in self.state.queues.values():
                q.promote_due(now)
            return self.state.fingerprint()

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def work_generation(self) -> int:
        return self._signal.generation

    def wait_for_work(self, timeout: float, seen: Optional[int] = None) -> int:
        return self._signal.wait(timeout, seen)
