"""Aligning a table onto a regular time grid."""
import math

from .. import types as T
from ..errors import QueryError
from ..table import Table
from ..timeutil import floor_to


def align(table, every, start=None, end=None):
    """One row per grid point ``start, start + every, ... < end`` holding the last row at or
    before that point.  Grid points before the first row get NaN in float columns and are
    dropped if the table has non-float value columns.

    ``start`` defaults to the first timestamp rounded down to the grid, ``end`` to one step
    past the last timestamp rounded down.
    """
    if every <= 0:
        raise QueryError("grid step must be positive")
    if table.num_rows == 0:
        return Table(table.schema)
    if not table.is_time_sorted():
        table = table.sort_by()
    ts = table.time_values()
    if start is None:
        start = floor_to(ts[0], every)
    if end is None:
        end = floor_to(ts[-1], every) + every
    all_float = all(c.type == T.FLOAT for c in table.schema.columns[1:])
    out = Table(table.schema)
    cols = out._cols
    j = -1
    t = start
    while t < end:
        while j + 1 < len(ts) and ts[j + 1] <= t:
            j += 1
        if j < 0:
            if all_float:
                cols[0].append(t)
                for col in cols[1:]:
                    col.append(math.nan)
        else:
            row = table.row(j)
            cols[0].append(t)
            for col, v in zip(cols[1:], row[1:]):
                col.append(v)
        t += every
    return out
