"""Rolling-window aggregates over time."""
import math
from collections import deque

from .. import types as T
from ..errors import QueryError
from ..schema import Column


def rolling(table, column, window, how="mean"):
    """Add a column ``<column>_rolling_<how>`` holding the aggregate of ``column``
    over the trailing time window ``(t - window, t]`` of each row.

    The table must be sorted by time.  ``how`` is ``mean``, ``sum``, ``min``,
    ``max`` or ``count``.  NaN values are skipped; a window with no usable
    value gives NaN (``count`` gives 0).
    """
    if window <= 0:
        raise QueryError("window must be positive")
    if how not in ("mean", "sum", "min", "max", "count"):
        raise QueryError(f"unknown rolling aggregate {how!r}")
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"rolling needs a numeric column, {column!r} is {col.type}")
    if not table.is_time_sorted():
        raise QueryError("rolling needs a table sorted by time")
    ts = table.time_values()
    values = table.column_view(column)
    buf = deque()
    out = []
    for t, v in zip(ts, values):
        buf.append((t, v))
        while buf and buf[0][0] <= t - window:
            buf.popleft()
        usable = [x for _, x in buf if not (isinstance(x, float) and math.isnan(x))]
        if how == "count":
            out.append(len(usable))
        elif not usable:
            out.append(math.nan)
        elif how == "mean":
            out.append(math.fsum(usable) / len(usable))
        elif how == "sum":
            out.append(float(math.fsum(usable)))
        elif how == "min":
            out.append(float(min(usable)))
        else:
            out.append(float(max(usable)))
    new_type = T.INT if how == "count" else T.FLOAT
    return table.with_column(Column(f"{column}_rolling_{how}", new_type), out)


def ewma(table, column, halflife):
    """Add ``<column>_ewma``: an exponentially weighted moving average in *time*.

    The weight of an earlier value decays by half every ``halflife``
    microseconds, so irregular sampling is handled correctly:
    ``m_i = m_(i-1) + (1 - 0.5 ** (dt / halflife)) * (x_i - m_(i-1))``.
    NaN values leave the average unchanged; the first non-NaN value starts it
    (rows before it get NaN).
    """
    if halflife <= 0:
        raise QueryError("halflife must be positive")
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"ewma needs a numeric column, {column!r} is {col.type}")
    if not table.is_time_sorted():
        raise QueryError("ewma needs a table sorted by time")
    out = []
    m = None
    last_t = None
    for t, v in zip(table.time_values(), table.column_view(column)):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(math.nan if m is None else m)
            continue
        if m is None:
            m = float(v)
        else:
            alpha = 1.0 - 0.5 ** ((t - last_t) / halflife)
            m = m + alpha * (float(v) - m)
        last_t = t
        out.append(m)
    return table.with_column(Column(f"{column}_ewma", T.FLOAT), out)
