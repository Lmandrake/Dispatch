"""Resampling: aggregate rows into fixed-width time buckets."""
from .. import agg as A
from .. import types as T
from ..errors import QueryError
from ..schema import Column, Schema
from ..table import Table
from ..timeutil import floor_to


def _plan(schema, aggs):
    """Normalise ``aggs`` into a list of ``(column, aggregate, output_name)``."""
    if isinstance(aggs, str):
        name = A.check_aggregate(aggs)
        aggs = {c.name: name for c in schema.columns[1:] if A.applies_to(name, c.type)}
        if not aggs:
            raise QueryError(f"no column can be aggregated with {name}")
    plan = []
    for col_name, spec in aggs.items():
        col = schema.column(col_name)
        if col.name == schema.time_column.name:
            raise QueryError("the time column cannot be aggregated")
        names = [spec] if isinstance(spec, str) else list(spec)
        for name in names:
            A.check_aggregate(name)
            if not A.applies_to(name, col.type):
                raise QueryError(f"aggregate {name} does not apply to {col.type} column {col.name!r}")
            plan.append((col, name, f"{col.name}_{name}"))
    if not plan:
        raise QueryError("nothing to aggregate")
    return plan


def resample(table, every, aggs="mean", origin=0):
    """Bucket rows by ``floor((t - origin) / every)`` and aggregate each bucket.

    ``every`` is the bucket width in microseconds (> 0).  ``aggs`` is either
    one aggregate name applied to every column it fits, or a mapping
    ``{column: name or [names]}``.  The result has the time column (the
    bucket start) followed by one ``<column>_<aggregate>`` column per pair,
    and one row per non-empty bucket in ascending time order.  Within a
    bucket, values are taken in input order (this matters for ``first`` and
    ``last``).
    """
    if every <= 0:
        raise QueryError("bucket width must be positive")
    schema = table.schema
    plan = _plan(schema, aggs)
    ts = table.time_values()
    buckets = {}
    for i, t in enumerate(ts):
        buckets.setdefault(floor_to(t, every, origin), []).append(i)
    out_cols = [Column(schema.time_column.name, T.TS)]
    for col, name, out_name in plan:
        out_cols.append(Column(out_name, A.result_type(name, col.type)))
    out_schema = Schema(out_cols)
    data = [[] for _ in out_cols]
    for start in sorted(buckets):
        idx = buckets[start]
        data[0].append(start)
        for k, (col, name, _) in enumerate(plan, start=1):
            values = table.column_view(col.name)
            data[k].append(A.apply(name, [values[i] for i in idx]))
    return Table(out_schema, data)
