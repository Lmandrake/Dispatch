"""Unicode sparklines for quick looks at a column in the terminal."""
import math

from . import types as T
from .errors import QueryError
from .ops.resample import resample

BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values, low=None, high=None):
    """One block character per value; NaN (and None) become a space."""
    finite = [v for v in values if v is not None and not math.isnan(v)]
    if not finite:
        return " " * len(values)
    lo = min(finite) if low is None else low
    hi = max(finite) if high is None else high
    span = hi - lo
    out = []
    for v in values:
        if v is None or math.isnan(v):
            out.append(" ")
            continue
        if span <= 0:
            out.append(BLOCKS[len(BLOCKS) // 2])
            continue
        k = int((min(max(v, lo), hi) - lo) / span * (len(BLOCKS) - 1) + 0.5)
        out.append(BLOCKS[k])
    return "".join(out)


def column_sparkline(table, column, width=60):
    """Resample ``column`` into at most ``width`` buckets by mean and draw them."""
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"sparkline needs a numeric column, {column!r} is {col.type}")
    if width < 1:
        raise QueryError("width must be at least 1")
    rng = table.time_range()
    if rng is None:
        return ""
    lo, hi = rng
    every = max((hi - lo) // width + 1, 1)
    r = resample(table, every, {column: "mean"}, origin=lo)
    return sparkline([v if v is not None else math.nan for v in r.column(f"{column}_mean")])
