"""As-of joins: attach to each left row the latest right row at or before it."""
import bisect

from ..errors import QueryError, SchemaError
from ..schema import Schema


def asof_join(left, right, tolerance=None, suffix="_right"):
    """Join ``right`` onto ``left`` by time.

    For each left row the matching right row is the last one (in time order)
    with ``right_time <= left_time`` and, when ``tolerance`` is given,
    ``left_time - right_time <= tolerance``.  Left rows without a match are
    dropped.  Right columns whose names clash with left columns get
    ``suffix`` appended; the right time column is not copied.
    """
    if tolerance is not None and tolerance < 0:
        raise QueryError("tolerance must not be negative")
    if not right.is_time_sorted():
        right = right.sort_by()
    rts = right.time_values()
    lnames = set(left.schema.names)
    extra = []
    for c in right.schema.columns[1:]:
        name = c.name if c.name not in lnames else c.name + suffix
        if name in lnames:
            raise SchemaError(f"column name clash for {c.name!r} even with suffix")
        extra.append((c, name))
    out_schema = Schema(list(left.schema.columns) +
                        [type(c)(name, c.type) for c, name in extra])
    keep = []
    match = []
    for i, t in enumerate(left.time_values()):
        j = bisect.bisect_right(rts, t) - 1
        if j < 0:
            continue
        if tolerance is not None and t - rts[j] > tolerance:
            continue
        keep.append(i)
        match.append(j)
    cols = [[left.column_view(c.name)[i] for i in keep] for c in left.schema]
    for c, _ in extra:
        src = right.column_view(c.name)
        cols.append([src[j] for j in match])
    from ..table import Table

    return Table._trusted(out_schema, cols)
