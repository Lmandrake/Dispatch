"""Largest-Triangle-Three-Buckets down-sampling for plotting.

Keeps ``threshold`` rows of a time-sorted table chosen so that a line plot of
``column`` against time looks like the original: the first and last rows are
always kept and each bucket in between contributes the row forming the
largest triangle with the previous kept row and the average of the next
bucket.  NaN values are treated as 0 when computing areas.
"""
import math

from .. import types as T
from ..errors import QueryError


def _y(v):
    if isinstance(v, float) and math.isnan(v):
        return 0.0
    return float(v)


def lttb_indices(xs, ys, threshold):
    n = len(xs)
    if threshold >= n or threshold == 0:
        return list(range(n))
    if threshold < 3:
        raise QueryError("LTTB needs a threshold of at least 3")
    every = (n - 2) / (threshold - 2)
    kept = [0]
    a = 0
    for i in range(threshold - 2):
        avg_start = int(math.floor((i + 1) * every)) + 1
        avg_end = min(int(math.floor((i + 2) * every)) + 1, n)
        span = range(avg_start, avg_end)
        if span:
            avg_x = math.fsum(xs[j] for j in span) / len(span)
            avg_y = math.fsum(ys[j] for j in span) / len(span)
        else:
            avg_x, avg_y = xs[n - 1], ys[n - 1]
        start = int(math.floor(i * every)) + 1
        end = int(math.floor((i + 1) * every)) + 1
        best = start
        best_area = -1.0
        ax, ay = xs[a], ys[a]
        for j in range(start, min(end, n - 1)):
            area = abs((ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay))
            if area > best_area:
                best_area = area
                best = j
        kept.append(best)
        a = best
    kept.append(n - 1)
    return kept


def lttb(table, column, threshold):
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"LTTB needs a numeric column, {column!r} is {col.type}")
    if threshold < 0:
        raise QueryError("threshold must not be negative")
    if not table.is_time_sorted():
        table = table.sort_by()
    xs = [float(t) for t in table.time_values()]
    ys = [_y(v) for v in table.column_view(column)]
    return table.take(lttb_indices(xs, ys, threshold))
