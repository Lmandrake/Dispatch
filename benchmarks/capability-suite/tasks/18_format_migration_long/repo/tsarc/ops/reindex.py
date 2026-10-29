"""Reindexing onto given timestamps with interpolation.

:func:`reindex` evaluates every float column of a table at new timestamps.
``nearest`` takes the value of the closest row (earlier row on a tie),
``previous`` the last row at or before the timestamp, ``linear`` interpolates
between the surrounding rows.  Timestamps outside the table's range give NaN
except with ``nearest``.
"""
import bisect
import math

from .. import types as T
from ..errors import QueryError
from ..schema import Column, Schema
from ..table import Table

METHODS = ("nearest", "previous", "linear")


def _value_at(ts, vals, t, method):
    n = len(ts)
    j = bisect.bisect_right(ts, t)
    if method == "previous":
        return vals[j - 1] if j > 0 else math.nan
    if method == "nearest":
        if j == 0:
            return vals[0]
        if j == n:
            return vals[-1]
        before, after = ts[j - 1], ts[j]
        return vals[j - 1] if t - before <= after - t else vals[j]
    # linear
    if j > 0 and ts[j - 1] == t:
        return vals[j - 1]
    if j == 0 or j == n:
        return math.nan
    t0, t1 = ts[j - 1], ts[j]
    v0, v1 = vals[j - 1], vals[j]
    return v0 + (v1 - v0) * ((t - t0) / (t1 - t0))


def reindex(table, timestamps, method="linear"):
    if method not in METHODS:
        raise QueryError(f"unknown reindex method {method!r} (expected one of {', '.join(METHODS)})")
    if table.num_rows == 0:
        raise QueryError("cannot reindex an empty table")
    if not table.is_time_sorted():
        table = table.sort_by()
    floats = [c for c in table.schema.columns[1:] if c.type == T.FLOAT]
    if not floats:
        raise QueryError("reindex needs at least one float column")
    ts = list(table.time_values())
    new_ts = sorted(timestamps)
    out_schema = Schema([Column(table.schema.time_column.name, T.TS)] + floats)
    cols = [new_ts]
    for c in floats:
        vals = table.column_view(c.name)
        cols.append([float(_value_at(ts, vals, t, method)) for t in new_ts])
    return Table(out_schema, cols)


def grid(start, end, every):
    if every <= 0:
        raise QueryError("grid step must be positive")
    return list(range(start, end, every))
