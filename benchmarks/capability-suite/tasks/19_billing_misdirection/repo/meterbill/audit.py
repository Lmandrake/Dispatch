"""Audit trail of billing runs (docs/RECONCILIATION.md, "Audit").

Every billing run that is exported appends one JSON line to
``<data dir>/audit.jsonl`` so Finance can see which run produced which
figures:

    {"cycle": "2026-03", "invoices": 12, "total_usd": "10674.14",
     "records": 1208, "rejects": 8, "digest": "<sha256 of the manifest>"}

``record_run`` builds the entry, ``append`` writes it, ``read_trail`` reads
the file back (skipping blank lines), and ``last_for`` returns the latest
entry for a cycle.  Two runs over the same data must produce the same
digest; ``compare_runs`` reports what differs between two entries.
"""

import hashlib
import json
from pathlib import Path

from .fx import REFERENCE
from .money import Money

FIELDS = ("cycle", "invoices", "total_usd", "due_usd", "records", "rejects", "digest")


def run_digest(run):
    """SHA-256 over every invoice's JSON rendering, in invoice-number order."""
    from .render import render
    h = hashlib.sha256()
    for inv in sorted(run.invoices, key=lambda i: i.number):
        h.update(render(inv, "json").encode("utf-8"))
    return h.hexdigest()


def record_run(run):
    total = Money.zero(REFERENCE)
    due = Money.zero(REFERENCE)
    for row in run.reconciliation():
        total = total + row.invoiced_usd
        due = due + row.due_usd
    return {
        "cycle": run.cycle,
        "invoices": len(run.invoices),
        "total_usd": f"{total.amount:f}",
        "due_usd": f"{due.amount:f}",
        "records": len(run.ingested.records),
        "rejects": len(run.ingested.rejects),
        "digest": run_digest(run),
    }


def append(path, entry):
    missing = [f for f in FIELDS if f not in entry]
    if missing:
        raise ValueError(f"audit entry lacks {', '.join(missing)}")
    p = Path(path)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def read_trail(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{p}:{lineno}: {e}") from None
    return out


def last_for(trail, cycle):
    found = [e for e in trail if e.get("cycle") == cycle]
    return found[-1] if found else None


def compare_runs(a, b):
    """Field names whose values differ between two audit entries."""
    return [f for f in FIELDS if a.get(f) != b.get(f)]
