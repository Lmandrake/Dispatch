"""Dead-letter tooling: inspect and act on failed jobs.

A job is "dead" when it is in state ``failed``. This module groups dead jobs
by their last error (so an operator sees "412 jobs failed with
ConnectionError: ..." rather than 412 lines), exports them as JSON lines for
offline analysis, and requeues them in bulk once the cause is fixed.

Error grouping normalises the message so that jobs failing for the same
reason group together: digits are replaced by ``#`` and hex strings of 8 or
more characters by ``<hex>``, then the text is cut at 120 characters.
"""

import re
from collections import OrderedDict
from typing import Dict, IO, Iterable, List, Optional

from . import codec
from .job import FAILED

_DIGITS = re.compile(r"\d+")
_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)


def error_signature(message: Optional[str]) -> str:
    if not message:
        return "(no error recorded)"
    text = _HEX.sub("<hex>", message)
    text = _DIGITS.sub("#", text)
    text = " ".join(text.split())
    return text[:120]


def dead_jobs(broker, queue: Optional[str] = None) -> List:
    return broker.jobs(queue=queue, state=FAILED)


def group_by_error(broker, queue: Optional[str] = None) -> "OrderedDict[str, List[str]]":
    """``{signature: [job ids]}``, largest group first (ties by signature)."""
    groups: Dict[str, List[str]] = {}
    for job in dead_jobs(broker, queue):
        groups.setdefault(error_signature(job.last_error), []).append(job.id)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return OrderedDict(ordered)


def export_jsonl(broker, out: IO[str], queue: Optional[str] = None) -> int:
    n = 0
    for job in dead_jobs(broker, queue):
        doc = {"id": job.id, "queue": job.queue, "kind": job.kind, "payload": job.payload,
               "attempts": job.attempts, "errors": job.errors, "finished_at": job.finished_at,
               "tags": job.tags}
        out.write(codec.dumps(doc) + "\n")
        n += 1
    return n


def requeue(broker, job_ids: Iterable[str]) -> Dict[str, List[str]]:
    report = {"requeued": [], "skipped": []}
    for job_id in job_ids:
        try:
            broker.retry(job_id)
            report["requeued"].append(job_id)
        except Exception:  # noqa: BLE001 - report and continue
            report["skipped"].append(job_id)
    return report


def requeue_signature(broker, signature: str, queue: Optional[str] = None) -> Dict[str, List[str]]:
    groups = group_by_error(broker, queue)
    return requeue(broker, groups.get(signature, []))


def render(broker, queue: Optional[str] = None) -> str:
    groups = group_by_error(broker, queue)
    if not groups:
        return "no dead jobs\n"
    lines = []
    for sig, ids in groups.items():
        sample = ", ".join(ids[:3]) + (" ..." if len(ids) > 3 else "")
        lines.append(f"{len(ids):>6}  {sig}")
        lines.append(f"        {sample}")
    return "\n".join(lines) + "\n"
