"""Calendar rollups: daily, weekly and monthly summaries in a fixed UTC offset.

Unlike :func:`tsarc.ops.resample`, buckets follow the calendar: a month is a
calendar month, a week starts on Monday, and a ``--tz +02:00`` offset moves the
bucket boundaries to local midnight.  Bucket start times are stored in UTC.
"""
import datetime as _dt

from . import agg as A
from . import types as T
from .errors import QueryError
from .schema import Column, Schema
from .table import Table
from .timeutil import US_PER_SECOND

PERIODS = ("day", "week", "month", "year")
_EPOCH = _dt.datetime(1970, 1, 1)


def _to_local(us, offset):
    return _EPOCH + _dt.timedelta(microseconds=us + offset)


def _to_utc_us(moment, offset):
    delta = moment - _EPOCH
    return (delta.days * 86400 + delta.seconds) * US_PER_SECOND + delta.microseconds - offset


def bucket_start(us, period, offset=0):
    m = _to_local(us, offset)
    if period == "day":
        start = _dt.datetime(m.year, m.month, m.day)
    elif period == "week":
        day = _dt.datetime(m.year, m.month, m.day)
        start = day - _dt.timedelta(days=day.weekday())
    elif period == "month":
        start = _dt.datetime(m.year, m.month, 1)
    elif period == "year":
        start = _dt.datetime(m.year, 1, 1)
    else:
        raise QueryError(f"unknown period {period!r} (expected one of {', '.join(PERIODS)})")
    return _to_utc_us(start, offset)


def rollup(table, period, aggs, offset=0):
    """One row per calendar bucket that has rows; columns as in resample."""
    schema = table.schema
    plan = []
    for name, spec in aggs.items():
        col = schema.column(name)
        for a in ([spec] if isinstance(spec, str) else spec):
            A.check_aggregate(a)
            if not A.applies_to(a, col.type):
                raise QueryError(f"aggregate {a} does not apply to {col.type} column {name!r}")
            plan.append((col, a))
    if not plan:
        raise QueryError("nothing to aggregate")
    groups = {}
    for i, t in enumerate(table.time_values()):
        groups.setdefault(bucket_start(t, period, offset), []).append(i)
    out_schema = Schema([Column(schema.time_column.name, T.TS)] +
                        [Column(f"{c.name}_{a}", A.result_type(a, c.type)) for c, a in plan])
    cols = [[] for _ in out_schema]
    for start in sorted(groups):
        idx = groups[start]
        cols[0].append(start)
        for k, (c, a) in enumerate(plan, start=1):
            vals = table.column_view(c.name)
            cols[k].append(A.apply(a, [vals[i] for i in idx]))
    return Table(out_schema, cols)


def bucket_label(us, period, offset=0):
    m = _to_local(us, offset)
    if period == "day":
        return m.strftime("%Y-%m-%d")
    if period == "week":
        iso = m.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if period == "month":
        return m.strftime("%Y-%m")
    return m.strftime("%Y")
