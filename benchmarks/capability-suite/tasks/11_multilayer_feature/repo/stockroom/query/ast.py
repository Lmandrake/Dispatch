"""Query syntax tree."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Compare:
    field: str      # canonical field name (aliases already resolved)
    op: str         # one of = != < <= > >= ~ in
    value: object   # raw text, or a tuple of raw texts for ``in``
    pos: int        # offset of the field token


@dataclass(frozen=True)
class Flag:
    """A bare boolean field such as ``low``."""

    field: str
    pos: int


@dataclass(frozen=True)
class And:
    left: object
    right: object


@dataclass(frozen=True)
class Or:
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    operand: object


def describe(node):
    """Render a tree back to (normalised) query text; used in tests and --explain."""
    if isinstance(node, Compare):
        if node.op == "in":
            return f"{node.field} in ({', '.join(_quote(v) for v in node.value)})"
        return f"{node.field} {node.op} {_quote(node.value)}"
    if isinstance(node, Flag):
        return node.field
    if isinstance(node, And):
        return f"({describe(node.left)} and {describe(node.right)})"
    if isinstance(node, Or):
        return f"({describe(node.left)} or {describe(node.right)})"
    if isinstance(node, Not):
        return f"not {describe(node.operand)}"
    raise TypeError(f"not a query node: {node!r}")


def _quote(value):
    text = str(value)
    if text and all(c.isalnum() or c in "_-./$:" for c in text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
