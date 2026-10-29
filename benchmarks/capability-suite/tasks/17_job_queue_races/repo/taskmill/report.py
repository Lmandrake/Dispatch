"""Plain-text reports for operators (``taskmill stats`` and friends).

``queue_table`` renders per-queue counts as an aligned table; ``lease_table``
the active leases with their remaining time; ``metrics_table`` a metrics
snapshot grouped by metric family. Column widths adapt to the content.
"""

from typing import Dict, List, Sequence

STATE_COLUMNS = ("pending", "delayed", "reserved", "done", "failed", "cancelled")


def table(headers: Sequence[str], rows: List[Sequence], align: str = None) -> str:
    """An aligned text table. ``align`` is one char per column: l or r (default: l then r...)."""
    cols = len(headers)
    if align is None:
        align = "l" + "r" * (cols - 1)
    cells = [[str(h) for h in headers]] + [["" if c is None else str(c) for c in row] for row in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(cols)]
    out = []
    for n, row in enumerate(cells):
        parts = []
        for i, c in enumerate(row):
            parts.append(c.ljust(widths[i]) if align[i] == "l" else c.rjust(widths[i]))
        out.append("  ".join(parts).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out) + "\n"


def queue_table(broker) -> str:
    rows = []
    totals = {s: 0 for s in STATE_COLUMNS}
    for name in broker.queue_names():
        st = broker.queue_stats(name)
        rows.append([name + (" *" if st["paused"] else "")] + [st[s] for s in STATE_COLUMNS])
        for s in STATE_COLUMNS:
            totals[s] += st[s]
    rows.append(["total"] + [totals[s] for s in STATE_COLUMNS])
    return table(["queue", *STATE_COLUMNS], rows)


def lease_table(broker) -> str:
    now = broker.clock()
    rows = []
    for l in broker.leases():
        rows.append([l["job_id"], l["worker"] or "-", f"{l['deadline'] - now:.1f}s"])
    return table(["job", "worker", "remaining"], rows)


def metrics_table(snapshot: Dict[str, float]) -> str:
    rows = []
    for name in sorted(snapshot):
        v = snapshot[name]
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        elif isinstance(v, float):
            v = f"{v:.6g}"
        rows.append([name, v])
    return table(["metric", "value"], rows)
