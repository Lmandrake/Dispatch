"""Text histograms of numeric columns."""
import math

from . import types as T
from .errors import QueryError
from .render import format_float

BAR = "#"


def histogram(values, bins=10, low=None, high=None):
    """``(edges, counts)`` with ``bins`` equal-width bins over ``[low, high]``.

    NaN values are ignored; the last bin includes its upper edge.  When every
    value is the same, a single bin of width 1 centred on it is used.
    """
    if bins < 1:
        raise QueryError("bins must be at least 1")
    vals = [float(v) for v in values if not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return [], []
    lo = min(vals) if low is None else float(low)
    hi = max(vals) if high is None else float(high)
    if hi < lo:
        raise QueryError("histogram upper bound is below the lower bound")
    if hi == lo:
        lo, hi, bins = lo - 0.5, hi + 0.5, 1
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins)] + [hi]
    counts = [0] * bins
    for v in vals:
        if v < lo or v > hi:
            continue
        k = int((v - lo) / width)
        if k >= bins:
            k = bins - 1
        counts[k] += 1
    return edges, counts


def render_histogram(table, column, bins=10, width=40):
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT, T.TS):
        raise QueryError(f"histogram needs a numeric column, {column!r} is {col.type}")
    edges, counts = histogram(table.column_view(column), bins)
    if not counts:
        return f"{column}: no values"
    top = max(counts)
    labels = [f"[{format_float(edges[i])}, {format_float(edges[i + 1])}" +
              ("]" if i == len(counts) - 1 else ")") for i in range(len(counts))]
    lw = max(len(s) for s in labels)
    cw = len(str(top))
    lines = []
    for label, c in zip(labels, counts):
        bar = BAR * (round(width * c / top) if top else 0)
        lines.append(f"{label.ljust(lw)}  {str(c).rjust(cw)}  {bar}".rstrip())
    return "\n".join(lines)
