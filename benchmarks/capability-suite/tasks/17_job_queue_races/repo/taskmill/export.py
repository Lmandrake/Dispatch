"""Export and import job sets as JSON lines.

``export_jobs`` writes one canonical JSON object per job (``Job.to_dict``
minus lease fields) to a text stream, sorted by job id. ``import_jobs``
enqueues the waiting jobs of such a file into another broker, for moving
work between deployments: finished jobs are skipped, reserved jobs are
imported as pending (their lease does not travel), and each job keeps its
queue, kind, payload, priority, tags and idempotency key. Ids are NOT
preserved (the target broker assigns its own); the mapping is returned.
"""

from typing import IO, Dict, Iterable, Optional

from . import codec
from .job import FINISHED, Job

LEASE_FIELDS = ("lease_token", "lease_deadline", "leased_at", "worker")


def export_jobs(broker, out: IO[str], queue: Optional[str] = None, states: Optional[Iterable[str]] = None) -> int:
    wanted = None if states is None else set(states)
    n = 0
    for job in broker.jobs(queue=queue):
        if wanted is not None and job.state not in wanted:
            continue
        d = job.to_dict()
        for f in LEASE_FIELDS:
            d.pop(f, None)
        out.write(codec.dumps(d) + "\n")
        n += 1
    return n


def import_jobs(broker, lines: Iterable[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = codec.loads(line)
        for f in LEASE_FIELDS:
            d.setdefault(f, None)
        job = Job.from_dict(d)
        if job.state in FINISHED:
            continue
        res = broker.enqueue(job.queue, job.kind, job.payload, priority=job.priority, tags=job.tags,
                             idempotency_key=job.idempotency_key, max_attempts=job.max_attempts,
                             run_at=job.run_at if job.state == "delayed" else None, backoff=job.backoff)
        mapping[job.id] = res.job_id
    return mapping
