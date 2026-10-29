"""Merging tables by time."""
import heapq

from ..errors import SchemaError
from ..table import Table


def merge_tables(tables):
    """Merge tables with identical schemas into one, ordered by time.

    Each input is first sorted by time (stably).  Rows with equal timestamps
    keep the order of the inputs they came from (earlier inputs first), then
    their order within that input.
    """
    tables = list(tables)
    if not tables:
        raise SchemaError("merge needs at least one table")
    schema = tables[0].schema
    for t in tables[1:]:
        if t.schema != schema:
            raise SchemaError(f"cannot merge tables with different schemas: {schema.to_text()} vs "
                              f"{t.schema.to_text()}")
    streams = []
    for k, t in enumerate(tables):
        st = t if t.is_time_sorted() else t.sort_by()
        streams.append(((row[0], k, i, row) for i, row in enumerate(st.rows())))
    out = Table(schema)
    cols = out._cols
    for _, _, _, row in heapq.merge(*streams):
        for col, v in zip(cols, row):
            col.append(v)
    return out
