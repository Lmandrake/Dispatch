"""Filling NaN values in float columns.

Methods:

``forward``      replace each NaN with the last earlier non-NaN value (leading NaNs stay)
``backward``     replace each NaN with the next later non-NaN value (trailing NaNs stay)
``linear``       interpolate linearly in *time* between the surrounding non-NaN values;
                 NaNs before the first or after the last value stay
``value``        replace every NaN with a constant
"""
import math

from . import types as T
from .errors import QueryError

METHODS = ("forward", "backward", "linear", "value")


def _is_missing(v):
    return isinstance(v, float) and math.isnan(v)


def fill_values(times, values, method, constant=None):
    out = list(values)
    n = len(out)
    if method == "forward":
        last = None
        for i in range(n):
            if _is_missing(out[i]):
                if last is not None:
                    out[i] = last
            else:
                last = out[i]
    elif method == "backward":
        nxt = None
        for i in range(n - 1, -1, -1):
            if _is_missing(out[i]):
                if nxt is not None:
                    out[i] = nxt
            else:
                nxt = out[i]
    elif method == "linear":
        known = [i for i in range(n) if not _is_missing(out[i])]
        for a, b in zip(known, known[1:]):
            if b - a < 2:
                continue
            t0, t1 = times[a], times[b]
            v0, v1 = out[a], out[b]
            for i in range(a + 1, b):
                if t1 == t0:
                    out[i] = v0
                else:
                    out[i] = v0 + (v1 - v0) * ((times[i] - t0) / (t1 - t0))
    elif method == "value":
        if constant is None:
            raise QueryError("fill method 'value' needs a constant")
        out = [float(constant) if _is_missing(v) else v for v in out]
    else:
        raise QueryError(f"unknown fill method {method!r} (expected one of {', '.join(METHODS)})")
    return out


def fill_table(table, columns=None, method="forward", constant=None):
    """A copy of ``table`` with NaNs filled in the given float columns (default: all)."""
    schema = table.schema
    if columns is None:
        columns = [c.name for c in schema if c.type == T.FLOAT]
    cols = table.columns()
    if method == "linear" and not table.is_time_sorted():
        raise QueryError("linear fill needs a table sorted by time")
    for name in columns:
        if schema.column(name).type != T.FLOAT:
            raise QueryError(f"fill only applies to float columns, {name!r} is "
                             f"{schema.column(name).type}")
        cols[name] = fill_values(table.time_values(), cols[name], method, constant)
    from .table import Table

    return Table(schema, cols)
