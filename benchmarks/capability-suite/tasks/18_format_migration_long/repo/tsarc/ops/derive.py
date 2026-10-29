"""Derived columns: add a column computed from an expression over each row.

``derive(table, "temp_f", "temp * 9 / 5 + 32")`` appends a float column.
The new column's type is the expression's static type (see
:mod:`tsarc.expr.compiler`); a ``bool`` expression gives a bool column.
"""
import math

from .. import types as T
from ..errors import QueryError
from ..expr import compile_value_expression
from ..schema import Column, check_column_name


def parse_assignment(text):
    """Parse ``name=expression``."""
    if "=" not in text:
        raise QueryError(f"derived column must look like name=expression, got {text!r}")
    name, expr = text.split("=", 1)
    name = name.strip()
    check_column_name(name)
    if not expr.strip():
        raise QueryError(f"empty expression for derived column {name!r}")
    return name, expr.strip()


def _canonical(type_, value):
    if type_ == T.FLOAT and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if type_ == T.INT and isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise QueryError("integer expression produced a non-finite value")
        return int(value)
    return value


def derive(table, name, expression, replace=False):
    """A copy of ``table`` with column ``name`` computed from ``expression``.

    With ``replace=True`` an existing column of that name is replaced (keeping its position,
    and its type must not change); otherwise an existing name is an error.
    """
    compiled = compile_value_expression(expression, table.schema)
    type_ = compiled.type
    values = [_canonical(type_, v) for v in compiled.values(table)]
    if name in table.schema:
        if not replace:
            raise QueryError(f"column {name!r} already exists (use replace)")
        old = table.schema.column(name)
        if old.type != type_:
            raise QueryError(f"cannot replace {old.type} column {name!r} with a {type_} expression")
        if name == table.schema.time_column.name:
            raise QueryError("the time column cannot be replaced")
        cols = table.columns()
        cols[name] = values
        from ..table import Table

        return Table(table.schema, cols)
    return table.with_column(Column(name, type_), values)


def derive_many(table, assignments, replace=False):
    """Apply several ``name=expression`` assignments in order (later ones see earlier ones)."""
    for text in assignments:
        name, expr = parse_assignment(text)
        table = derive(table, name, expr, replace=replace)
    return table
