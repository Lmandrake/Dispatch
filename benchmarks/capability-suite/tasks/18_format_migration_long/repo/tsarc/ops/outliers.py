"""Outlier detection on numeric columns.

Two methods:

``zscore``  a value is an outlier when ``|x - mean| > k * stdev`` (population stdev)
``mad``     robust: ``|x - median| > k * 1.4826 * MAD`` where MAD is the median absolute
            deviation

NaN values are never outliers and are excluded from the statistics.
"""
import math
import statistics

from .. import types as T
from ..errors import QueryError

METHODS = ("zscore", "mad")


def _finite(values):
    return [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]


def outlier_mask(values, method="mad", k=3.5):
    if k <= 0:
        raise QueryError("k must be positive")
    vals = _finite(values)
    if len(vals) < 3:
        return [False] * len(values)
    if method == "zscore":
        mean = math.fsum(vals) / len(vals)
        sd = math.sqrt(math.fsum((v - mean) ** 2 for v in vals) / len(vals))
        if sd == 0:
            return [False] * len(values)
        centre, scale = mean, sd
    elif method == "mad":
        med = statistics.median(vals)
        mad = statistics.median(abs(v - med) for v in vals)
        if mad == 0:
            return [False] * len(values)
        centre, scale = med, 1.4826 * mad
    else:
        raise QueryError(f"unknown outlier method {method!r} (expected one of {', '.join(METHODS)})")
    out = []
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(False)
        else:
            out.append(abs(float(v) - centre) > k * scale)
    return out


def find_outliers(table, column, method="mad", k=3.5):
    """Row indices of outliers in ``column``."""
    col = table.schema.column(column)
    if col.type not in (T.INT, T.FLOAT):
        raise QueryError(f"outlier detection needs a numeric column, {column!r} is {col.type}")
    mask = outlier_mask(table.column_view(column), method, k)
    return [i for i, m in enumerate(mask) if m]


def drop_outliers(table, column, method="mad", k=3.5):
    bad = set(find_outliers(table, column, method, k))
    return table.take(i for i in range(table.num_rows) if i not in bad)
