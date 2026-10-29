"""Hourly and daily usage rollups in the customer's own timezone.

A rollup answers "how much did customer X use of metric Y in this hour (or
this local day)?".  Records are bucketed by the *local* wall-clock hour or
calendar date of their UTC instant in the customer's timezone, and each
bucket's quantity is the metric's own aggregation of the records in it
(``Metric.aggregate``):

    sum   total of the records in the bucket
    max   the largest reading in the bucket
    last  the latest reading in the bucket

Consequences worth knowing: the daily value of a ``max`` metric is the peak
of the day, not the sum of hourly peaks, and the rollup of a ``last`` metric
is the closing reading of the bucket.  Buckets with no records are not
emitted (``fill_gaps=True`` on ``daily`` adds zero-record days between the
first and last day of a series).  On a DST change the local day has 23 or 25
hours; hourly buckets are keyed by the UTC instant that starts them so the
repeated 01:00 of a fall-back night stays two distinct buckets.

This module only groups; it does not decide which records belong to a
billing period (usage.py) nor how a quantity is priced (pricing.py).
"""

from dataclasses import dataclass
from datetime import timedelta

from .csvutil import write_rows
from .render.fmt import format_qty
from .timeutil import local_date, zone


@dataclass(frozen=True)
class Rollup:
    customer: str
    metric: str
    bucket: str          # "2026-03-05" (daily) or "2026-03-05T14:00" local (hourly)
    start_utc: object    # first instant of the bucket, UTC
    quantity: object     # Decimal
    records: int


def _hour_start_utc(instant):
    return instant.replace(minute=0, second=0, microsecond=0)


def _local_hour_label(start_utc, tz):
    return start_utc.astimezone(zone(tz)).strftime("%Y-%m-%dT%H:00")


def _group(records, key):
    groups = {}
    for r in records:
        groups.setdefault(key(r), []).append(r)
    return groups


def hourly(records, timezones, metrics):
    """Hourly rollups.

    ``timezones`` maps customer id -> IANA zone name (a plain ``dict`` or
    ``{c.id: c.timezone for c in customers}``); ``metrics`` is a MetricSet.
    Records of customers missing from ``timezones`` raise KeyError.  Sorted by
    customer, metric, instant.
    """
    out = []
    groups = _group(records, lambda r: (r.customer, r.metric, _hour_start_utc(r.at)))
    for (cid, mid, start), recs in groups.items():
        qty = metrics.get(mid).aggregate(sorted(recs, key=lambda r: r.at))
        out.append(Rollup(cid, mid, _local_hour_label(start, timezones[cid]), start, qty, len(recs)))
    out.sort(key=lambda r: (r.customer, r.metric, r.start_utc))
    return out


def daily(records, timezones, metrics, *, fill_gaps=False):
    """Daily rollups by local calendar date; see the module docstring."""
    out = []
    groups = _group(records, lambda r: (r.customer, r.metric, local_date(r.at, timezones[r.customer])))
    series = {}
    for (cid, mid, day), recs in groups.items():
        qty = metrics.get(mid).aggregate(sorted(recs, key=lambda r: r.at))
        start = min(r.at for r in recs)
        roll = Rollup(cid, mid, day.isoformat(), start, qty, len(recs))
        series.setdefault((cid, mid), {})[day] = roll
    for (cid, mid), days in series.items():
        ordered = sorted(days)
        if fill_gaps:
            day = ordered[0]
            while day <= ordered[-1]:
                if day not in days:
                    days[day] = Rollup(cid, mid, day.isoformat(), None, metrics.get(mid).aggregate([]), 0)
                day += timedelta(days=1)
            ordered = sorted(days)
        out.extend(days[d] for d in ordered)
    out.sort(key=lambda r: (r.customer, r.metric, r.bucket))
    return out


def peak(rollups):
    """The rollup with the largest quantity (ties: earliest bucket); None if empty."""
    best = None
    for r in rollups:
        if best is None or r.quantity > best.quantity:
            best = r
    return best


def total_records(rollups):
    return sum(r.records for r in rollups)


CSV_HEADER = ("customer", "metric", "bucket", "quantity", "records")


def rollups_to_csv(rollups, metrics):
    """CSV text, one row per rollup, quantities at the metric's display precision
    without thousands grouping (so spreadsheets read them as numbers)."""
    rows = []
    for r in rollups:
        precision = metrics.get(r.metric).precision
        rows.append((r.customer, r.metric, r.bucket, format_qty(r.quantity, precision).replace(",", ""),
                     r.records))
    return write_rows(CSV_HEADER, rows)


def render_rollups(rollups, metrics):
    """Fixed-width text table for a terminal."""
    if not rollups:
        return "No usage.\n"
    lines = [f"{'customer':<10}{'metric':<14}{'bucket':<18}{'quantity':>16}{'records':>9}"]
    for r in rollups:
        q = format_qty(r.quantity, metrics.get(r.metric).precision)
        lines.append(f"{r.customer:<10}{r.metric:<14}{r.bucket:<18}{q:>16}{r.records:>9}")
    return "\n".join(lines) + "\n"
