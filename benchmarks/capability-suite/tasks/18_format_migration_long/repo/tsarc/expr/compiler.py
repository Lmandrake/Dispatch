"""Type-check an expression against a schema and turn it into a Python closure.

Static typing rules:

* arithmetic (``+ - * / %``) needs numbers; ``int op int`` is ``int`` except
  ``/`` which is always ``float``; ``ts - ts`` is ``int`` (microseconds),
  ``ts + int`` / ``ts - int`` is ``ts``;
* comparisons need both sides of compatible types (numbers with numbers,
  text with text, bool with bool); a text literal compared with a ``ts``
  value is parsed as a timestamp;
* ``~`` needs text on the left and a text literal (a regular expression) on
  the right;
* ``and`` / ``or`` / ``not`` need booleans, and the whole expression must be
  boolean.

Errors are reported as :class:`~tsarc.errors.ExpressionError` with the
position of the offending node.
"""
import operator
import re

from .. import types as T
from ..errors import ExpressionError, SchemaError
from ..timeutil import parse_ts
from . import ast as A
from .functions import FUNCTIONS
from .parser import parse

NUMERIC = {T.INT, T.FLOAT, T.TS}

_CMP = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _lit_type(v):
    if isinstance(v, bool):
        return T.BOOL
    if isinstance(v, int):
        return T.INT
    if isinstance(v, float):
        return T.FLOAT
    return T.STR


class _Compiler:
    def __init__(self, schema):
        self.schema = schema

    def compile(self, node):
        """Return ``(type, fn)`` where ``fn(row_dict) -> value``."""
        method = getattr(self, "c_" + type(node).__name__)
        return method(node)

    def c_Literal(self, node):
        v = node.value
        return _lit_type(v), (lambda row, v=v: v)

    def c_Name(self, node):
        if node.name not in self.schema:
            raise ExpressionError(f"unknown column {node.name!r}", node.pos)
        type_ = self.schema.column(node.name).type
        name = node.name
        return type_, (lambda row, name=name: row[name])

    def c_Unary(self, node):
        type_, fn = self.compile(node.operand)
        if type_ not in (T.INT, T.FLOAT):
            raise ExpressionError(f"cannot negate a {type_} value", node.pos)
        return type_, (lambda row: -fn(row))

    def c_Binary(self, node):
        lt, lf = self.compile(node.left)
        rt, rf = self.compile(node.right)
        op = node.op
        if lt not in NUMERIC or rt not in NUMERIC:
            raise ExpressionError(f"operator {op!r} needs numbers, got {lt} and {rt}", node.pos)
        if T.TS in (lt, rt):
            if op == "-" and lt == T.TS and rt == T.TS:
                result = T.INT
            elif op in "+-" and lt == T.TS and rt == T.INT:
                result = T.TS
            elif op == "+" and lt == T.INT and rt == T.TS:
                result = T.TS
            else:
                raise ExpressionError(f"operator {op!r} is not defined for {lt} and {rt}", node.pos)
        elif op == "/":
            result = T.FLOAT
        elif T.FLOAT in (lt, rt):
            result = T.FLOAT
        else:
            result = T.INT
        if op == "+":
            fn = lambda row: lf(row) + rf(row)  # noqa: E731
        elif op == "-":
            fn = lambda row: lf(row) - rf(row)  # noqa: E731
        elif op == "*":
            fn = lambda row: lf(row) * rf(row)  # noqa: E731
        elif op == "/":
            def fn(row):
                d = rf(row)
                if d == 0:
                    return float("nan")
                return lf(row) / d
        else:
            def fn(row):
                d = rf(row)
                if d == 0:
                    return float("nan") if result == T.FLOAT else 0
                return lf(row) % d
        return result, fn

    def _coerce_pair(self, node, left, right):
        """Compile both sides of a comparison, converting text literals for ts columns."""
        lt, lf = self.compile(left)
        if lt == T.TS and isinstance(right, A.Literal) and isinstance(right.value, str):
            try:
                v = parse_ts(right.value)
            except SchemaError as exc:
                raise ExpressionError(str(exc), right.pos) from None
            return lt, lf, T.TS, (lambda row, v=v: v)
        rt, rf = self.compile(right)
        if rt == T.TS and isinstance(left, A.Literal) and isinstance(left.value, str):
            try:
                v = parse_ts(left.value)
            except SchemaError as exc:
                raise ExpressionError(str(exc), left.pos) from None
            return T.TS, (lambda row, v=v: v), rt, rf
        return lt, lf, rt, rf

    def _check_comparable(self, lt, rt, pos):
        if lt in NUMERIC and rt in NUMERIC:
            return
        if lt == rt:
            return
        raise ExpressionError(f"cannot compare {lt} with {rt}", pos)

    def c_Compare(self, node):
        if node.op == "~":
            lt, lf = self.compile(node.left)
            if lt != T.STR:
                raise ExpressionError("'~' needs a text value on the left", node.pos)
            if not (isinstance(node.right, A.Literal) and isinstance(node.right.value, str)):
                raise ExpressionError("'~' needs a text pattern on the right", node.right.pos)
            try:
                rx = re.compile(node.right.value)
            except re.error as exc:
                raise ExpressionError(f"bad regular expression: {exc}", node.right.pos) from None
            return T.BOOL, (lambda row: rx.search(lf(row)) is not None)
        lt, lf, rt, rf = self._coerce_pair(node, node.left, node.right)
        self._check_comparable(lt, rt, node.pos)
        if lt in (T.STR, T.BOOL) and node.op not in ("=", "!="):
            if lt == T.BOOL:
                raise ExpressionError(f"operator {node.op!r} is not defined for bool", node.pos)
        cmp = _CMP[node.op]
        return T.BOOL, (lambda row: cmp(lf(row), rf(row)))

    def c_InList(self, node):
        ot, of = self.compile(node.operand)
        values = []
        for item in node.items:
            v = item.value
            if ot == T.TS and isinstance(v, str):
                try:
                    v = parse_ts(v)
                except SchemaError as exc:
                    raise ExpressionError(str(exc), item.pos) from None
            self._check_comparable(ot, T.TS if ot == T.TS and isinstance(v, int) else _lit_type(v),
                                   item.pos)
            values.append(v)
        vs = tuple(values)
        return T.BOOL, (lambda row: of(row) in vs)

    def c_Between(self, node):
        ot, of, lt, lf = self._coerce_pair(node, node.operand, node.low)
        _, _, ht, hf = self._coerce_pair(node, node.operand, node.high)
        self._check_comparable(ot, lt, node.pos)
        self._check_comparable(ot, ht, node.pos)
        if ot == T.BOOL:
            raise ExpressionError("between is not defined for bool", node.pos)

        def fn(row):
            v = of(row)
            return lf(row) <= v <= hf(row)
        return T.BOOL, fn

    def c_BoolOp(self, node):
        parts = []
        for o in node.operands:
            t, f = self.compile(o)
            if t != T.BOOL:
                raise ExpressionError(f"'{node.op}' needs boolean operands, got {t}", o.pos)
            parts.append(f)
        if node.op == "and":
            return T.BOOL, (lambda row: all(f(row) for f in parts))
        return T.BOOL, (lambda row: any(f(row) for f in parts))

    def c_Not(self, node):
        t, f = self.compile(node.operand)
        if t != T.BOOL:
            raise ExpressionError(f"'not' needs a boolean operand, got {t}", node.pos)
        return T.BOOL, (lambda row: not f(row))

    def c_Call(self, node):
        if node.func not in FUNCTIONS:
            raise ExpressionError(f"unknown function {node.func!r}", node.pos)
        arity, result, impl, arg_types = FUNCTIONS[node.func]
        if len(node.args) != arity:
            raise ExpressionError(f"{node.func}() takes {arity} argument(s), got {len(node.args)}",
                                  node.pos)
        fns = []
        types = []
        for a, allowed in zip(node.args, arg_types):
            t, f = self.compile(a)
            if allowed is not None and t not in allowed:
                raise ExpressionError(f"{node.func}() does not accept a {t} argument", a.pos)
            fns.append(f)
            types.append(t)
        if result == "same":
            result = types[0]
        if arity == 1:
            f0 = fns[0]
            return result, (lambda row: impl(f0(row)))
        return result, (lambda row: impl(*(f(row) for f in fns)))


class CompiledExpression:
    """A type-checked boolean expression bound to a schema."""

    def __init__(self, text, schema, ast, fn):
        self.text = text
        self.schema = schema
        self.ast = ast
        self._fn = fn

    @property
    def columns(self):
        return A.names_used(self.ast)

    def __call__(self, row):
        return bool(self._fn(row))

    def mask(self, table):
        names = table.schema.names
        return [bool(self._fn(dict(zip(names, r)))) for r in table.rows()]

    def __repr__(self):
        return f"CompiledExpression({self.text!r})"


def compile_expression(text, schema):
    ast = parse(text)
    type_, fn = _Compiler(schema).compile(ast)
    if type_ != T.BOOL:
        raise ExpressionError(f"a filter must be a boolean expression, this one is {type_}", 0)
    return CompiledExpression(text, schema, ast, fn)


class CompiledValueExpression:
    """A type-checked expression of any type bound to a schema (used by ``derive``)."""

    def __init__(self, text, schema, ast, type_, fn):
        self.text = text
        self.schema = schema
        self.ast = ast
        self.type = type_
        self._fn = fn

    def __call__(self, row):
        return self._fn(row)

    def values(self, table):
        names = table.schema.names
        return [self._fn(dict(zip(names, r))) for r in table.rows()]


def compile_value_expression(text, schema):
    ast = parse(text)
    type_, fn = _Compiler(schema).compile(ast)
    return CompiledValueExpression(text, schema, ast, type_, fn)
