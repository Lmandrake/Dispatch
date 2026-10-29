"""Bulk operations: enqueue many jobs, cancel or retry by filter.

``enqueue_many(broker, items)`` enqueues each item (a dict with the
:meth:`Broker.enqueue` arguments plus ``queue`` and ``kind``) independently
and returns one :class:`BulkResult` per item, in order. A bad item does not
stop the others: its result carries the error instead of a job id.

``cancel_where`` and ``retry_where`` apply an operator action to every job
matching a filter (queue, state, kind, tag) and report what happened.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .errors import TaskmillError, ValidationError

ENQUEUE_FIELDS = {"queue", "kind", "payload", "priority", "delay", "run_at", "idempotency_key",
                  "max_attempts", "tags", "backoff"}


@dataclass(frozen=True)
class BulkResult:
    index: int
    job_id: Optional[str] = None
    created: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "job_id": self.job_id, "created": self.created, "error": self.error}


def enqueue_many(broker, items: Iterable[Dict[str, Any]]) -> List[BulkResult]:
    out = []
    for i, item in enumerate(items):
        try:
            if not isinstance(item, dict):
                raise ValidationError("item must be an object")
            extra = sorted(set(item) - ENQUEUE_FIELDS)
            if extra:
                raise ValidationError(f"unknown field(s): {', '.join(extra)}")
            if "queue" not in item or "kind" not in item:
                raise ValidationError("queue and kind are required")
            kw = dict(item)
            queue = kw.pop("queue")
            kind = kw.pop("kind")
            payload = kw.pop("payload", None)
            res = broker.enqueue(queue, kind, payload, **kw)
            out.append(BulkResult(i, res.job_id, res.created))
        except TaskmillError as exc:
            out.append(BulkResult(i, error=f"{type(exc).__name__}: {exc}"))
    return out


def _matches(job, queue, state, kind, tag) -> bool:
    return ((queue is None or job.queue == queue) and (state is None or job.state == state)
            and (kind is None or job.kind == kind) and (tag is None or tag in job.tags))


def select(broker, queue: Optional[str] = None, state: Optional[str] = None, kind: Optional[str] = None,
           tag: Optional[str] = None) -> List[str]:
    return [j.id for j in broker.jobs(queue=queue, state=state) if _matches(j, queue, state, kind, tag)]


def cancel_where(broker, **filters) -> Dict[str, List[str]]:
    report = {"cancelled": [], "skipped": []}
    for job_id in select(broker, **filters):
        try:
            (report["cancelled"] if broker.cancel(job_id) else report["skipped"]).append(job_id)
        except TaskmillError:
            report["skipped"].append(job_id)
    return report


def retry_where(broker, **filters) -> Dict[str, List[str]]:
    report = {"retried": [], "skipped": []}
    for job_id in select(broker, **filters):
        try:
            broker.retry(job_id)
            report["retried"].append(job_id)
        except TaskmillError:
            report["skipped"].append(job_id)
    return report
