"""Per-column statistics.

:func:`column_stats` returns one :class:`ColumnStats` per column.  For
numeric columns (``ts``, ``int``, ``float``) ``min``/``max`` ignore NaN and
``mean`` is :func:`math.fsum` divided by the count of non-NaN values; for
``str`` columns ``min``/``max`` are by code point and ``distinct`` is the
number of distinct values; for ``bool`` columns ``true`` counts the True
values.
"""
import math
from dataclasses import dataclass

from . import types as T
from .render import format_float, render_table
from .timeutil import US_PER_SECOND, format_ts


@dataclass
class ColumnStats:
    name: str
    type: str
    count: int
    min: object = None
    max: object = None
    mean: object = None
    distinct: object = None
    true: object = None
    nan: int = 0


def safe_mean(vals):
    """fsum-based mean; NaN when the values include both infinities."""
    try:
        return math.fsum(vals) / len(vals)
    except ValueError:
        return math.nan


def _stats_for(column, values):
    st = ColumnStats(column.name, column.type, len(values))
    if column.type in (T.TS, T.INT, T.FLOAT):
        vals = values
        if column.type == T.FLOAT:
            vals = [v for v in values if not math.isnan(v)]
            st.nan = len(values) - len(vals)
        if vals:
            st.min = min(vals)
            st.max = max(vals)
            if column.type != T.TS:
                st.mean = safe_mean(vals)
    elif column.type == T.STR:
        if values:
            st.min = min(values)
            st.max = max(values)
        st.distinct = len(set(values))
    elif column.type == T.BOOL:
        st.true = sum(1 for v in values if v)
    return st


def column_stats(table):
    return [_stats_for(c, table.column_view(c.name)) for c in table.schema]


def time_stats(table):
    """``(first, last, span_seconds, rows_per_second)``; None for an empty table.

    ``rows_per_second`` is None when the span is zero.
    """
    ts = table.time_values()
    if not ts:
        return None
    first, last = min(ts), max(ts)
    span = (last - first) / US_PER_SECOND
    rate = (len(ts) - 1) / span if span > 0 else None
    return first, last, span, rate


def _cell(type_, value):
    if value is None:
        return "-"
    if type_ == T.TS:
        return format_ts(value)
    if isinstance(value, float):
        return format_float(value)
    return str(value)


def render_stats(table):
    """The table printed by ``tsarc stats``."""
    rows = []
    for st in column_stats(table):
        if st.type == T.STR:
            extra = f"distinct={st.distinct}"
        elif st.type == T.BOOL:
            extra = f"true={st.true}"
        elif st.type == T.FLOAT and st.nan:
            extra = f"nan={st.nan}"
        else:
            extra = ""
        rows.append([
            st.name, st.type, str(st.count),
            _cell(st.type if st.type != T.BOOL else T.STR, st.min if st.type != T.BOOL else None),
            _cell(st.type if st.type != T.BOOL else T.STR, st.max if st.type != T.BOOL else None),
            _cell(T.FLOAT, st.mean),
            extra,
        ])
    return render_table(["column", "type", "count", "min", "max", "mean", "notes"], rows,
                        align="llrllrl")
