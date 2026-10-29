"""Comparing the distributions of a column in two tables (``tsarc compare``).

Reports, for each numeric column present in both tables with the same type:
the count, mean and standard deviation on each side, the difference of means,
and the two-sample Kolmogorov-Smirnov statistic D (the largest gap between the
two empirical CDFs).  NaN values are ignored.
"""
import bisect
import math
from dataclasses import dataclass

from . import types as T
from .render import format_float, render_table


@dataclass
class ColumnComparison:
    name: str
    left_count: int
    right_count: int
    left_mean: object
    right_mean: object
    left_std: object
    right_std: object
    ks: object

    @property
    def mean_diff(self):
        if self.left_mean is None or self.right_mean is None:
            return None
        return self.right_mean - self.left_mean


def _clean(values):
    return [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]


def _mean_std(vals):
    if not vals:
        return None, None
    m = math.fsum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    var = math.fsum((v - m) ** 2 for v in vals) / (len(vals) - 1)
    return m, math.sqrt(var)


def ks_statistic(a, b):
    if not a or not b:
        return None
    a = sorted(a)
    b = sorted(b)
    d = 0.0
    for x in sorted(set(a) | set(b)):
        fa = bisect.bisect_right(a, x) / len(a)
        fb = bisect.bisect_right(b, x) / len(b)
        d = max(d, abs(fa - fb))
    return d


def compare_tables(left, right):
    out = []
    for c in left.schema.columns[1:]:
        if c.type not in (T.INT, T.FLOAT):
            continue
        if c.name not in right.schema or right.schema.column(c.name).type != c.type:
            continue
        a = _clean(left.column_view(c.name))
        b = _clean(right.column_view(c.name))
        lm, ls = _mean_std(a)
        rm, rs = _mean_std(b)
        out.append(ColumnComparison(c.name, len(a), len(b), lm, rm, ls, rs, ks_statistic(a, b)))
    return out


def render(comparisons):
    def f(v):
        return "-" if v is None else format_float(v)

    rows = [[c.name, str(c.left_count), str(c.right_count), f(c.left_mean), f(c.right_mean),
             f(c.mean_diff), f(c.left_std), f(c.right_std), f(c.ks)] for c in comparisons]
    return render_table(["column", "n_a", "n_b", "mean_a", "mean_b", "diff", "std_a", "std_b", "ks"],
                        rows, align="lrrrrrrrr")
