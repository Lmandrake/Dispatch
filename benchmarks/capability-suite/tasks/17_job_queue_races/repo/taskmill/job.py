"""The Job record and its state machine.

States
------
``pending``    ready to be reserved (in its queue's ready heap).
``delayed``    waiting for ``run_at`` (first run in the future, or a retry
               waiting out its backoff). It becomes ready at ``run_at``.
``reserved``   leased to a worker until ``lease_deadline``.
``done``       acked; ``result`` holds the handler's return value.
``failed``     dead: a permanent error, or ``max_attempts`` deliveries used up.
``cancelled``  cancelled by an operator or a client.

``done``, ``failed`` and ``cancelled`` are terminal ("finished"); finished
jobs are purged ``retention`` seconds after ``finished_at``.

Allowed transitions (anything else raises InvalidTransition):

    pending   -> reserved | cancelled
    delayed   -> pending (time passes) | cancelled
    reserved  -> done | delayed (retry) | pending (lease expired) | failed | cancelled
    failed    -> pending (operator retry)
    cancelled -> pending (operator retry)

``attempts`` counts deliveries: it is incremented when the job is reserved.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .errors import InvalidTransition

PENDING = "pending"
DELAYED = "delayed"
RESERVED = "reserved"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

STATES = (PENDING, DELAYED, RESERVED, DONE, FAILED, CANCELLED)
FINISHED = frozenset({DONE, FAILED, CANCELLED})
WAITING = frozenset({PENDING, DELAYED})

TRANSITIONS = {
    PENDING: {RESERVED, CANCELLED},
    DELAYED: {PENDING, CANCELLED},
    RESERVED: {DONE, DELAYED, PENDING, FAILED, CANCELLED},
    DONE: set(),
    FAILED: {PENDING},
    CANCELLED: {PENDING},
}


def check_transition(job_id: str, old: str, new: str) -> None:
    if new not in TRANSITIONS.get(old, ()):
        raise InvalidTransition(f"{job_id}: cannot go from {old} to {new}")


@dataclass
class Job:
    id: str
    queue: str
    kind: str
    payload: Any = None
    priority: int = 5
    state: str = PENDING
    seq: int = 0                      # enqueue sequence number, the final tie-break
    enqueued_at: float = 0.0
    run_at: float = 0.0               # not ready before this time
    ready_at: float = 0.0             # when it became (or becomes) ready: the ordering time
    attempts: int = 0
    max_attempts: int = 5
    idempotency_key: Optional[str] = None   # normalised form
    tags: List[str] = field(default_factory=list)
    result: Any = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    finished_at: Optional[float] = None
    lease_token: Optional[str] = None
    lease_deadline: Optional[float] = None
    leased_at: Optional[float] = None
    worker: Optional[str] = None
    backoff: Optional[dict] = None    # per-job override of the queue's policy
    tenant: Optional[str] = None

    # ---------------------------------------------------------------- state

    @property
    def finished(self) -> bool:
        return self.state in FINISHED

    def transition(self, new: str) -> None:
        check_transition(self.id, self.state, new)
        self.state = new

    def add_error(self, at: float, message: str, keep: int) -> None:
        self.errors.append({"attempt": self.attempts, "at": at, "message": message})
        if keep >= 0 and len(self.errors) > keep:
            del self.errors[: len(self.errors) - keep]

    def clear_lease(self) -> None:
        self.lease_token = None
        self.lease_deadline = None
        self.leased_at = None
        self.worker = None

    @property
    def attempts_left(self) -> int:
        return self.max_attempts - self.attempts

    @property
    def last_error(self) -> Optional[str]:
        return self.errors[-1]["message"] if self.errors else None

    # ------------------------------------------------------------ (de)serialise

    FIELDS = ("id", "queue", "kind", "payload", "priority", "state", "seq", "enqueued_at", "run_at",
              "ready_at", "attempts", "max_attempts", "idempotency_key", "tags", "result", "errors",
              "finished_at", "lease_token", "lease_deadline", "leased_at", "worker", "backoff", "tenant")

    def to_dict(self) -> Dict[str, Any]:
        d = {name: getattr(self, name) for name in self.FIELDS}
        d["tags"] = list(self.tags)
        d["errors"] = [dict(e) for e in self.errors]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Job":
        unknown = set(d) - set(cls.FIELDS)
        if unknown:
            raise ValueError(f"unknown job field(s): {', '.join(sorted(unknown))}")
        if d.get("state", PENDING) not in STATES:
            raise ValueError(f"bad job state {d.get('state')!r}")
        kw = dict(d)
        kw["tags"] = list(kw.get("tags") or [])
        kw["errors"] = [dict(e) for e in kw.get("errors") or []]
        return cls(**kw)

    def summary(self) -> Dict[str, Any]:
        """The short form used by listings."""
        return {
            "id": self.id,
            "queue": self.queue,
            "kind": self.kind,
            "state": self.state,
            "priority": self.priority,
            "attempts": self.attempts,
            "run_at": self.run_at,
            "tenant": self.tenant,
        }

    def __repr__(self) -> str:
        return f"Job({self.id} {self.queue}/{self.kind} {self.state} p{self.priority} a{self.attempts})"


def validate_priority(priority) -> int:
    from .errors import ValidationError
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 9:
        raise ValidationError("priority must be an integer 0 (most urgent) to 9")
    return priority


def validate_kind(kind) -> str:
    from .errors import ValidationError
    if not isinstance(kind, str) or not kind or len(kind) > 100 or not kind.replace("_", "a").replace(".", "a").isalnum():
        raise ValidationError(f"bad job kind {kind!r}: use letters, digits, '_' and '.'")
    return kind


def validate_tenant(tenant) -> Optional[str]:
    import re
    from .errors import ValidationError
    if tenant is None:
        return None
    if not isinstance(tenant, str) or not re.match(r"^[a-z0-9][a-z0-9_.-]{0,63}$", tenant):
        raise ValidationError(f"bad tenant {tenant!r}: use 1-64 of a-z 0-9 _ . - (starting with a letter or digit)")
    return tenant


def validate_tags(tags) -> List[str]:
    from .errors import ValidationError
    if tags is None:
        return []
    if isinstance(tags, str) or not all(isinstance(t, str) and t and len(t) <= 64 for t in tags):
        raise ValidationError("tags must be a list of non-empty strings of at most 64 characters")
    out = []
    for t in tags:
        if t not in out:
            out.append(t)
    return out
