"""Turn a query syntax tree into a predicate over Items.

Values are converted (and type-checked) once, at compile time, so a bad
value is reported even if no item would ever reach that comparison.
"""

import operator

from stockroom.query import fields as F
from stockroom.query.ast import And, Compare, Flag, Not, Or
from stockroom.query.parser import parse

_CMP = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _always(_item):
    return True


def compile_node(node):
    if node is None:
        return _always
    if isinstance(node, And):
        left, right = compile_node(node.left), compile_node(node.right)
        return lambda it: left(it) and right(it)
    if isinstance(node, Or):
        left, right = compile_node(node.left), compile_node(node.right)
        return lambda it: left(it) or right(it)
    if isinstance(node, Not):
        inner = compile_node(node.operand)
        return lambda it: not inner(it)
    if isinstance(node, Flag):
        getter = F.FIELDS[node.field].getter
        return lambda it: bool(getter(it))
    if isinstance(node, Compare):
        return _compile_compare(node)
    raise TypeError(f"not a query node: {node!r}")


def _compile_compare(node):
    field = F.FIELDS[node.field]
    get = field.getter
    if node.op == "in":
        wanted = frozenset(F.convert(field, v, node.pos) for v in node.value)
        return lambda it: get(it) in wanted
    if node.op == "~":
        needle = str(node.value).lower()
        return lambda it: needle in str(get(it)).lower()
    value = F.convert(field, node.value, node.pos)
    cmp = _CMP[node.op]
    return lambda it: cmp(get(it), value)


def compile_query(text):
    """Parse and compile ``text``; returns ``predicate(item) -> bool``."""
    return compile_node(parse(text or ""))


def filter_items(items, text):
    pred = compile_query(text)
    return [it for it in items if pred(it)]
