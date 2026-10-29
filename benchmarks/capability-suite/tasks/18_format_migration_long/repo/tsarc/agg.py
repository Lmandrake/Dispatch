"""Aggregate functions used by ``stats`` and ``resample``.

Each aggregate takes a list of values of one column type and returns a value
(or None when the list is empty).  ``mean`` and ``sum`` use
:func:`math.fsum` so results do not depend on the order of the values.
"""
import math

from . import types as T
from .errors import QueryError

AGGREGATES = ("mean", "min", "max", "sum", "count", "first", "last")


def _numeric(type_):
    return type_ in (T.INT, T.FLOAT, T.TS)


def agg_count(values):
    return len(values)


def agg_first(values):
    return values[0] if values else None


def agg_last(values):
    return values[-1] if values else None


def agg_min(values):
    vals = [v for v in values if not (isinstance(v, float) and math.isnan(v))]
    return min(vals) if vals else None


def agg_max(values):
    vals = [v for v in values if not (isinstance(v, float) and math.isnan(v))]
    return max(vals) if vals else None


def agg_sum(values):
    if not values:
        return None
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return sum(values)
    try:
        return math.fsum(values)
    except ValueError:
        return math.nan


def agg_mean(values):
    if not values:
        return None
    try:
        return math.fsum(values) / len(values)
    except ValueError:  # both infinities present
        return math.nan


FUNCS = {
    "mean": agg_mean,
    "min": agg_min,
    "max": agg_max,
    "sum": agg_sum,
    "count": agg_count,
    "first": agg_first,
    "last": agg_last,
}


def check_aggregate(name):
    if name not in FUNCS:
        raise QueryError(f"unknown aggregate {name!r} (expected one of {', '.join(AGGREGATES)})")
    return name


def applies_to(name, type_):
    """Whether aggregate ``name`` can be applied to a column of ``type_``."""
    if name in ("count", "first", "last"):
        return True
    if name in ("min", "max"):
        return type_ != T.BOOL
    return type_ in (T.INT, T.FLOAT)


def result_type(name, type_):
    """Column type of the aggregate's result."""
    if name == "count":
        return T.INT
    if name == "mean":
        return T.FLOAT
    if name == "sum":
        return type_
    return type_


def apply(name, values):
    return FUNCS[name](values)
