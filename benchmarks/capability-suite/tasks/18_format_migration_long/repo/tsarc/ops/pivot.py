"""Long-to-wide pivot: one column per distinct key value."""
from .. import types as T
from ..errors import QueryError
from ..schema import Column, Schema, check_column_name
from ..table import Table


def pivot(table, key, value):
    """Turn rows ``(t, key, value)`` into rows ``(t, value_for_key1, value_for_key2, ...)``.

    ``key`` must be a str column; its distinct values (sorted) become column names,
    which must be valid column names.  ``value`` must be a float column.  Timestamps
    become unique and sorted; a missing combination is NaN.  If a (time, key) pair
    occurs more than once the last value wins.
    """
    schema = table.schema
    kc = schema.column(key)
    vc = schema.column(value)
    if kc.type != T.STR:
        raise QueryError(f"pivot key must be a str column, {key!r} is {kc.type}")
    if vc.type != T.FLOAT:
        raise QueryError(f"pivot value must be a float column, {value!r} is {vc.type}")
    keys = sorted(set(table.column_view(key)))
    for k in keys:
        check_column_name(k)
    tname = schema.time_column.name
    if tname in keys:
        raise QueryError(f"pivot key value {tname!r} clashes with the time column")
    cells = {}
    for t, k, v in zip(table.time_values(), table.column_view(key), table.column_view(value)):
        cells[(t, k)] = v
    times = sorted({t for t, _ in cells})
    out_schema = Schema([Column(tname, T.TS)] + [Column(k, T.FLOAT) for k in keys])
    cols = [times] + [[cells.get((t, k), float("nan")) for t in times] for k in keys]
    return Table(out_schema, cols)
