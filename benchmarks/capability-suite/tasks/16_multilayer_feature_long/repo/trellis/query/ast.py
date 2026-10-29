"""Syntax tree for parsed queries.

Nodes are frozen dataclasses so parsed queries can be compared in tests and
cached.  ``Compare.values`` is a tuple: one value for ordinary operators,
one or more for ``in``.  ``Flag`` is a bare boolean field (``overdue``).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Compare:
    field: str
    op: str
    values: tuple
    pos: int = 0


@dataclass(frozen=True)
class Flag:
    field: str
    pos: int = 0


@dataclass(frozen=True)
class Not:
    operand: object


@dataclass(frozen=True)
class And:
    left: object
    right: object


@dataclass(frozen=True)
class Or:
    left: object
    right: object


def walk(node):
    """Yield every node of the tree, parents before children."""
    if node is None:
        return
    yield node
    if isinstance(node, Not):
        yield from walk(node.operand)
    elif isinstance(node, (And, Or)):
        yield from walk(node.left)
        yield from walk(node.right)


def fields_used(node):
    """Canonical names of every field the query refers to."""
    return sorted({n.field for n in walk(node) if isinstance(n, (Compare, Flag))})


def to_text(node):
    """Render a tree back to query text (fully parenthesised)."""
    if node is None:
        return ""
    if isinstance(node, Flag):
        return node.field
    if isinstance(node, Compare):
        vals = [_quote(v) for v in node.values]
        if node.op == "in":
            return f"{node.field} in ({', '.join(vals)})"
        return f"{node.field} {node.op} {vals[0]}"
    if isinstance(node, Not):
        return f"not {to_text(node.operand)}"
    if isinstance(node, And):
        return f"({to_text(node.left)} and {to_text(node.right)})"
    if isinstance(node, Or):
        return f"({to_text(node.left)} or {to_text(node.right)})"
    raise TypeError(node)


def _quote(value):
    text = str(value)
    if text and all(c.isalnum() or c in "_-./+:@" for c in text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
