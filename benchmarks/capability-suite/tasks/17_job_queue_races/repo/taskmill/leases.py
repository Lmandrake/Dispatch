"""Lease bookkeeping: tokens, deadlines and retired tokens (rules: docs/LEASES.md)."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .errors import LeaseLost


@dataclass
class Lease:
    job_id: str
    token: str
    worker: Optional[str]
    issued_at: float
    deadline: float

    def to_dict(self) -> dict:
        return {"job_id": self.job_id, "token": self.token, "worker": self.worker,
                "issued_at": self.issued_at, "deadline": self.deadline}


@dataclass
class _Retired:
    job_id: str
    why: str          # "released" | "expired" | "cancelled"
    at: float


class LeaseTable:
    def __init__(self, retired_ttl: float = 600.0):
        self.retired_ttl = retired_ttl
        self._by_job: Dict[str, Lease] = {}
        # token -> job_id, for current AND retired tokens
        self._by_token: Dict[str, str] = {}
        self._retired: Dict[str, _Retired] = {}

    # ------------------------------------------------------------- granting

    def grant(self, job_id: str, token: str, worker: Optional[str], now: float, deadline: float) -> Lease:
        old = self._by_job.get(job_id)
        if old is not None:
            self._retire(old.token, job_id, "superseded", now)
        lease = Lease(job_id, token, worker, now, deadline)
        self._by_job[job_id] = lease
        self._by_token[token] = job_id
        return lease

    def _retire(self, token: str, job_id: str, why: str, now: float) -> None:
        self._retired[token] = _Retired(job_id, why, now)
        self._by_token[token] = job_id

    def release(self, job_id: str, now: float, why: str = "released") -> Optional[Lease]:
        """End the job's current lease (ack, nack, cancel, expiry)."""
        lease = self._by_job.pop(job_id, None)
        if lease is not None:
            self._retire(lease.token, job_id, why, now)
        return lease

    def set_deadline(self, job_id: str, deadline: float) -> None:
        lease = self._by_job.get(job_id)
        if lease is not None:
            lease.deadline = deadline

    # ------------------------------------------------------------ validation

    def _lost(self, token: str, now: float) -> LeaseLost:
        r = self._retired.get(token)
        if r is None:
            return LeaseLost("unknown lease token")
        if r.why == "superseded":
            return LeaseLost(f"{r.job_id}: lease superseded by a newer delivery")
        return LeaseLost(f"{r.job_id}: lease {r.why}")

    def resolve(self, token: str, now: float) -> Lease:
        """The current, unexpired lease for ``token``, or LeaseLost."""
        job_id = self._by_token.get(token)
        if job_id is None:
            raise LeaseLost("unknown lease token")
        lease = self._by_job.get(job_id)
        if lease is None or lease.token != token:
            raise self._lost(token, now)
        if now >= lease.deadline:
            raise LeaseLost(f"{job_id}: lease expired at {lease.deadline:.3f}")
        return lease

    def renewal(self, token: str, now: float, extend: float, max_total: float) -> Tuple[Lease, float]:
        """Validate a heartbeat and compute the new deadline (not applied yet)."""
        job_id = self._by_token.get(token)
        if job_id is None:
            raise LeaseLost("unknown lease token")
        lease = self._by_job.get(job_id)
        if lease is None:
            raise self._lost(token, now)
        if now >= lease.deadline:
            raise LeaseLost(f"{job_id}: lease expired at {lease.deadline:.3f}")
        deadline = min(now + extend, lease.issued_at + max_total)
        return lease, max(deadline, lease.deadline)

    # --------------------------------------------------------------- queries

    def get(self, job_id: str) -> Optional[Lease]:
        return self._by_job.get(job_id)

    def expired(self, now: float) -> List[Lease]:
        """Current leases whose deadline has passed, earliest deadline first."""
        out = [l for l in self._by_job.values() if now >= l.deadline]
        out.sort(key=lambda l: (l.deadline, l.job_id))
        return out

    def next_deadline(self) -> Optional[float]:
        return min((l.deadline for l in self._by_job.values()), default=None)

    def active(self) -> List[Lease]:
        return sorted(self._by_job.values(), key=lambda l: (l.deadline, l.job_id))

    def __len__(self) -> int:
        return len(self._by_job)

    def prune_retired(self, now: float) -> int:
        """Forget retired tokens older than ``retired_ttl``."""
        dead = [t for t, r in self._retired.items() if now - r.at >= self.retired_ttl]
        for t in dead:
            del self._retired[t]
            if self._by_token.get(t) is not None and t not in {l.token for l in self._by_job.values()}:
                del self._by_token[t]
        return len(dead)

    def clear(self) -> None:
        self._by_job.clear()
        self._by_token.clear()
        self._retired.clear()
