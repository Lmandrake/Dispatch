"""Flow statistics derived from the audit trail (``trellis stats``).

For each issue of a project that is ``done``, the *lead time* is the time
from its ``issue.created`` event to the ``issue.transitioned`` event that
last moved it to ``done``; the *cycle time* runs from the first time it
entered ``in_progress`` to that same event (issues that never went through
``in_progress`` have no cycle time).  Times are whole hours, rounded down.

``flow_stats`` returns per-issue rows; ``summarize`` turns a list of hours
into count / median / p85 / max, using the nearest-rank method for
percentiles so the numbers are always actual observations.
"""

import math
from dataclasses import dataclass

from trellis.clock import parse_timestamp


@dataclass(frozen=True)
class FlowRow:
    key: str
    lead_hours: int
    cycle_hours: int | None


def _hours(start, end):
    delta = parse_timestamp(end) - parse_timestamp(start)
    return int(delta.total_seconds() // 3600)


def flow_stats(tracker, project_key):
    project = tracker.project(project_key)
    events = tracker.audit.events(project=project.key)
    created, started, finished = {}, {}, {}
    for ev in events:
        if ev.action == "issue.created":
            created.setdefault(ev.subject, ev.timestamp)
        elif ev.action == "issue.transitioned":
            to = ev.details.get("to")
            if to == "in_progress":
                started.setdefault(ev.subject, ev.timestamp)
            if to == "done":
                finished[ev.subject] = ev.timestamp
            elif ev.details.get("from") == "done":
                finished.pop(ev.subject, None)
    rows = []
    for issue in tracker.repo.list_issues(project.key):
        if issue.status != "done" or issue.key not in finished or issue.key not in created:
            continue
        end = finished[issue.key]
        start = started.get(issue.key)
        rows.append(FlowRow(issue.key, _hours(created[issue.key], end),
                            _hours(start, end) if start and start <= end else None))
    return rows


def percentile(values, pct):
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"count": 0, "median": None, "p85": None, "max": None}
    return {"count": len(values), "median": percentile(values, 50),
            "p85": percentile(values, 85), "max": max(values)}


def render_stats(rows):
    from trellis.table import render_table

    lead = summarize([r.lead_hours for r in rows])
    cycle = summarize([r.cycle_hours for r in rows])

    def cell(v):
        return "-" if v is None else f"{v}h"

    table = render_table(
        ["Measure", "Count", "Median", "P85", "Max"],
        [["lead time", lead["count"], cell(lead["median"]), cell(lead["p85"]), cell(lead["max"])],
         ["cycle time", cycle["count"], cell(cycle["median"]), cell(cycle["p85"]), cell(cycle["max"])]],
        align="lrrrr")
    return table + "\n"
