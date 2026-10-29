"""Group rows by the values of key columns and aggregate the rest.

``groupby(table, ["site"], {"temp": ["mean", "max"]})`` gives one row per
distinct ``site`` with columns ``site``, ``temp_mean``, ``temp_max`` and
``rows``.  The result is not a time-indexed table (its first column is a
key), so it is returned as a list of dicts plus the output column names,
ready for :func:`tsarc.render.render_table` or CSV.
"""
from .. import agg as A
from .. import types as T
from ..errors import QueryError


def _plan(schema, keys, aggs):
    for k in keys:
        col = schema.column(k)
        if col.type == T.FLOAT:
            raise QueryError(f"cannot group by float column {k!r}")
    plan = []
    for name, spec in aggs.items():
        col = schema.column(name)
        if name in keys:
            raise QueryError(f"column {name!r} is a group key")
        for a in ([spec] if isinstance(spec, str) else spec):
            A.check_aggregate(a)
            if not A.applies_to(a, col.type):
                raise QueryError(f"aggregate {a} does not apply to {col.type} column {name!r}")
            plan.append((col, a, f"{name}_{a}"))
    return plan


def groupby(table, keys, aggs, sort=True):
    """Return ``(column_names, rows)``; rows are dicts in key order (or first-seen order
    when ``sort`` is false)."""
    keys = [keys] if isinstance(keys, str) else list(keys)
    if not keys:
        raise QueryError("groupby needs at least one key column")
    schema = table.schema
    plan = _plan(schema, keys, aggs)
    key_cols = [table.column_view(k) for k in keys]
    groups = {}
    for i in range(table.num_rows):
        groups.setdefault(tuple(c[i] for c in key_cols), []).append(i)
    order = list(groups)
    if sort:
        key_types = [schema.column(k).type for k in keys]
        order.sort(key=lambda g: tuple(T.sort_key(t, v) for t, v in zip(key_types, g)))
    names = keys + [out for _, _, out in plan] + ["rows"]
    rows = []
    for g in order:
        idx = groups[g]
        row = dict(zip(keys, g))
        for col, a, out in plan:
            values = table.column_view(col.name)
            row[out] = A.apply(a, [values[i] for i in idx])
        row["rows"] = len(idx)
        rows.append(row)
    return names, rows


def format_rows(names, rows, schema):
    """Text cells for :func:`render_table`."""
    from ..render import format_float

    out = []
    for r in rows:
        cells = []
        for n in names:
            v = r[n]
            if v is None:
                cells.append("-")
            elif n in schema and schema.column(n).type == T.TS:
                cells.append(T.format_text(T.TS, v))
            elif isinstance(v, float):
                cells.append(format_float(v))
            elif isinstance(v, bool):
                cells.append("true" if v else "false")
            else:
                cells.append(str(v))
        out.append(cells)
    return out
