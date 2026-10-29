"""ASCII line charts for the terminal (``tsarc plot``).

The chart is ``height`` text rows by ``width`` columns.  Each column covers an
equal slice of the time range and shows the mean of the values falling in it
as a ``*``; empty slices are blank.  A y-axis with the min and max labels is
drawn on the left and the first/last timestamps below.
"""
import math

from . import types as T
from .errors import QueryError
from .render import format_float
from .timeutil import format_ts


def _bucket_means(ts, values, width):
    lo, hi = min(ts), max(ts)
    span = hi - lo
    sums = [0.0] * width
    counts = [0] * width
    for t, v in zip(ts, values):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        k = 0 if span == 0 else min(int((t - lo) * width / (span + 1)), width - 1)
        sums[k] += v
        counts[k] += 1
    return [s / c if c else None for s, c in zip(sums, counts)]


def line_chart(table, column, width=60, height=12):
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"plot needs a numeric column, {column!r} is {col.type}")
    if width < 2 or height < 2:
        raise QueryError("chart must be at least 2 x 2")
    ts = table.time_values()
    if not ts:
        return f"{column}: no rows"
    means = _bucket_means(ts, table.column_view(column), width)
    present = [m for m in means if m is not None]
    if not present:
        return f"{column}: no values"
    lo, hi = min(present), max(present)
    grid = [[" "] * width for _ in range(height)]
    for x, m in enumerate(means):
        if m is None:
            continue
        y = 0 if hi == lo else round((m - lo) / (hi - lo) * (height - 1))
        grid[height - 1 - y][x] = "*"
    top, bottom = format_float(hi), format_float(lo)
    lw = max(len(top), len(bottom))
    lines = []
    for r, row in enumerate(grid):
        label = top if r == 0 else bottom if r == height - 1 else ""
        lines.append(f"{label.rjust(lw)} |{''.join(row)}".rstrip())
    lines.append(" " * lw + " +" + "-" * width)
    first, last = format_ts(min(ts)), format_ts(max(ts))
    pad = max(width - len(first) - len(last), 1)
    lines.append(" " * (lw + 2) + first + " " * pad + last)
    return "\n".join(lines)
