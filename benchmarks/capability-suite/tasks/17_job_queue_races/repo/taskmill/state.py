"""Broker state and the record appliers shared by live operations and replay.

The broker never mutates jobs directly. Every change is expressed as a WAL
record (a dict with ``seq`` and ``op``) and applied with :meth:`State.apply`,
both when the change happens and when it is replayed after a crash.

Appliers trust the record: validation (does the caller hold the lease? is the
key free?) is done by the broker before it creates the record. Appliers only
check that the job exists and that the state transition is allowed, and raise
:class:`ReplayError` otherwise, because a record that does not fit the state
means the log and the state have diverged.

Record ops
----------
``enqueue``   job (full Job dict)
``reserve``   id, token, worker, at, deadline           attempts += 1
``heartbeat`` id, token, deadline
``ack``       id, token, result, at
``retry``     id, token, run_at, error, at              -> delayed
``fail``      id, token, error, at                      -> failed
``expire``    id, token, at, to ("pending" | "failed")
``cancel``    id, at, from (the state being cancelled)
``release``   id, token, at                             -> pending, attempts -= 1
``requeue``   id, at                                    operator retry, attempts reset
``priority``  id, priority
``pause``     queue, paused
``purge``     ids
"""

from typing import Callable, Dict, Iterable, List, Optional

from . import codec
from .config import BrokerConfig
from .errors import TaskmillError
from .idempotency import IdempotencyIndex
from .ids import job_id_sort_key, parse_job_id
from .job import (CANCELLED, DELAYED, DONE, FAILED, FINISHED, PENDING, RESERVED, Job, check_transition)
from .leases import LeaseTable
from .pqueue import JobQueue


class ReplayError(TaskmillError):
    """A record does not fit the state it is applied to."""


class State:
    def __init__(self, config: BrokerConfig):
        self.config = config
        self.jobs: Dict[str, Job] = {}
        self.queues: Dict[str, JobQueue] = {}
        self.paused: set = set()
        self.next_id = 1
        self.leases = LeaseTable(config.retired_token_ttl)
        self.idem = IdempotencyIndex()
        self.last_seq = 0
        self._appliers: Dict[str, Callable[[dict], List[str]]] = {
            "enqueue": self._enqueue,
            "reserve": self._reserve,
            "heartbeat": self._heartbeat,
            "ack": self._ack,
            "retry": self._retry,
            "fail": self._fail,
            "expire": self._expire,
            "cancel": self._cancel,
            "release": self._release,
            "requeue": self._requeue,
            "priority": self._priority,
            "pause": self._pause,
            "purge": self._purge,
        }

    # ------------------------------------------------------------- helpers

    def queue(self, name: str) -> JobQueue:
        q = self.queues.get(name)
        if q is None:
            q = self.queues[name] = JobQueue(name)
        return q

    def job(self, job_id: str) -> Job:
        j = self.jobs.get(job_id)
        if j is None:
            raise ReplayError(f"record refers to unknown job {job_id}")
        return j

    def _move(self, job: Job, new: str) -> None:
        try:
            check_transition(job.id, job.state, new)
        except TaskmillError as exc:
            raise ReplayError(str(exc)) from exc
        job.state = new

    def _finish(self, job: Job, at: float) -> None:
        job.finished_at = at
        if job.idempotency_key is not None:
            self.idem.finished(job.id, at + self.config.dedup_window)

    # --------------------------------------------------------------- apply

    def apply(self, record: dict) -> List[str]:
        """Apply one record. Returns the ids of jobs that became finished."""
        op = record.get("op")
        fn = self._appliers.get(op)
        if fn is None:
            raise ReplayError(f"unknown record op {op!r}")
        finished = fn(record)
        seq = record["seq"]
        if seq > self.last_seq:
            self.last_seq = seq
        return finished

    def _enqueue(self, r: dict) -> List[str]:
        job = Job.from_dict(r["job"])
        if job.id in self.jobs:
            raise ReplayError(f"job {job.id} enqueued twice")
        self.jobs[job.id] = job
        _, n = parse_job_id(job.id)
        self.next_id = max(self.next_id, n + 1)
        if job.idempotency_key is not None:
            self.idem.claim(job.queue, job.idempotency_key, job.id)
        self.queue(job.queue).push(job)
        return []

    def _reserve(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        if job.state == DELAYED and job.run_at <= r["at"]:
            # Delayed -> pending happens by the clock, without a record of its own.
            self.queue(job.queue).discard(job.id)
            job.state = PENDING
        if job.state != PENDING:
            raise ReplayError(f"{job.id}: reserve while {job.state}")
        self.queue(job.queue).discard(job.id)
        self._move(job, RESERVED)
        job.attempts += 1
        job.lease_token = r["token"]
        job.lease_deadline = r["deadline"]
        job.leased_at = r["at"]
        job.worker = r.get("worker")
        self.leases.grant(job.id, r["token"], r.get("worker"), r["at"], r["deadline"])
        return []

    def _heartbeat(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        if job.state != RESERVED:
            raise ReplayError(f"{job.id}: heartbeat while {job.state}")
        job.lease_deadline = r["deadline"]
        self.leases.set_deadline(job.id, r["deadline"])
        return []

    def _ack(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        self._move(job, DONE)
        job.result = r.get("result")
        job.clear_lease()
        self.leases.release(job.id, r["at"])
        self._finish(job, r["at"])
        return [job.id]

    def _retry(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        self._move(job, DELAYED)
        if r.get("error"):
            job.add_error(r["at"], r["error"], self.config.max_errors_kept)
        job.run_at = r["run_at"]
        job.ready_at = r["run_at"]
        job.clear_lease()
        self.leases.release(job.id, r["at"])
        self.queue(job.queue).push(job)
        return []

    def _fail(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        self._move(job, FAILED)
        if r.get("error"):
            job.add_error(r["at"], r["error"], self.config.max_errors_kept)
        job.clear_lease()
        self.leases.release(job.id, r["at"])
        self._finish(job, r["at"])
        return [job.id]

    def _expire(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        to = r.get("to", PENDING)
        if job.state != RESERVED:
            raise ReplayError(f"{job.id}: expire while {job.state}")
        deadline = job.lease_deadline if job.lease_deadline is not None else r["at"]
        job.add_error(r["at"], "lease expired", self.config.max_errors_kept)
        job.clear_lease()
        self.leases.release(job.id, r["at"], why="expired")
        if to == FAILED:
            self._move(job, FAILED)
            self._finish(job, r["at"])
            return [job.id]
        self._move(job, PENDING)
        job.ready_at = deadline
        self.queue(job.queue).push(job)
        return []

    def _release(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        self._move(job, PENDING)
        job.attempts -= 1
        job.clear_lease()
        self.leases.release(job.id, r["at"])
        self.queue(job.queue).push(job)
        return []

    def _cancel(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        was = r.get("from", job.state)
        self._move(job, CANCELLED)
        if was in (PENDING, DELAYED):
            self.queue(job.queue).discard(job.id)
        if was == RESERVED:
            self.leases.release(job.id, r["at"], why="cancelled")
        job.clear_lease()
        self._finish(job, r["at"])
        return [job.id]

    def _requeue(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        self._move(job, PENDING)
        job.attempts = 0
        job.finished_at = None
        job.result = None
        job.run_at = r["at"]
        job.ready_at = r["at"]
        if job.idempotency_key is not None:
            self.idem.reopened(job.id)
        self.queue(job.queue).push(job)
        return []

    def _priority(self, r: dict) -> List[str]:
        job = self.job(r["id"])
        job.priority = r["priority"]
        if job.state in (PENDING, DELAYED):
            self.queue(job.queue).push(job)   # re-push with the new key; the old entry goes dead
        return []

    def _pause(self, r: dict) -> List[str]:
        if r["paused"]:
            self.paused.add(r["queue"])
        else:
            self.paused.discard(r["queue"])
        self.queue(r["queue"])
        return []

    def _purge(self, r: dict) -> List[str]:
        for job_id in r["ids"]:
            job = self.jobs.pop(job_id, None)
            if job is None:
                continue
            self.queue(job.queue).discard(job_id)
            self.idem.drop(job_id)
        return []

    # ------------------------------------------------------------ snapshots

    def export_jobs(self) -> List[dict]:
        return [self.jobs[k].to_dict() for k in sorted(self.jobs, key=job_id_sort_key)]

    def export_queues(self) -> Dict[str, dict]:
        return {name: {"paused": name in self.paused} for name in sorted(self.queues)}

    def load(self, jobs: Iterable[dict], queues: Dict[str, dict], next_id: int, last_seq: int) -> None:
        """Replace everything with a snapshot's content."""
        self.jobs.clear()
        self.queues.clear()
        self.paused.clear()
        self.leases.clear()
        self.idem.clear()
        for name, info in queues.items():
            self.queue(name)
            if info.get("paused"):
                self.paused.add(name)
        for d in jobs:
            job = Job.from_dict(d)
            self.jobs[job.id] = job
            if job.state in (PENDING, DELAYED):
                self.queue(job.queue).push(job)
            else:
                self.queue(job.queue)
            if job.state == RESERVED and job.lease_token:
                self.leases.grant(job.id, job.lease_token, job.worker,
                                  job.leased_at if job.leased_at is not None else 0.0, job.lease_deadline)
            if job.idempotency_key is not None:
                self.idem.claim(job.queue, job.idempotency_key, job.id)
                if job.state in FINISHED and job.finished_at is not None:
                    self.idem.finished(job.id, job.finished_at + self.config.dedup_window)
        self.next_id = next_id
        self.last_seq = last_seq

    # ------------------------------------------------------------- queries

    def counts(self, queue: str) -> Dict[str, int]:
        c = {s: 0 for s in (PENDING, DELAYED, RESERVED, DONE, FAILED, CANCELLED)}
        for j in self.jobs.values():
            if j.queue == queue:
                c[j.state] += 1
        return c

    def fingerprint(self) -> List[dict]:
        """A comparable view of every job (used by ``taskmill recover --check`` and tests)."""
        return [codec.roundtrip(d) for d in self.export_jobs()]

    def find(self, queue: Optional[str] = None, state: Optional[str] = None) -> List[Job]:
        out = [j for j in self.jobs.values()
               if (queue is None or j.queue == queue) and (state is None or j.state == state)]
        out.sort(key=lambda j: job_id_sort_key(j.id))
        return out
