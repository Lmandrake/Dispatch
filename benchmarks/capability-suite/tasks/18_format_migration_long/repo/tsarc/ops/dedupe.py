"""Removing duplicate rows."""
from .. import types as T
from ..errors import QueryError


def _key(types, row):
    return tuple(("f", T.float_bits(v)) if t == T.FLOAT and v is not None else v
                 for t, v in zip(types, row))


def dedupe(table, columns=None, keep="first"):
    """Drop rows that repeat an earlier (``keep="first"``) or later (``keep="last"``) row.

    Two rows are duplicates when they are equal in every column of
    ``columns`` (default: all columns).  Floats compare by bit pattern, so
    NaN duplicates NaN.  The surviving rows keep their original order.
    """
    if keep not in ("first", "last"):
        raise QueryError("keep must be 'first' or 'last'")
    schema = table.schema
    names = schema.names if columns is None else list(columns)
    idx = [schema.index(n) for n in names]
    types = [schema[i].type for i in idx]
    order = range(table.num_rows)
    if keep == "last":
        order = reversed(order)
    seen = set()
    kept = []
    for i in order:
        row = table.row(i)
        k = _key(types, [row[j] for j in idx])
        if k in seen:
            continue
        seen.add(k)
        kept.append(i)
    kept.sort()
    return table.take(kept)
