"""Expression syntax tree."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Literal:
    value: object
    pos: int


@dataclass(frozen=True)
class Name:
    name: str
    pos: int


@dataclass(frozen=True)
class Call:
    func: str
    args: tuple
    pos: int


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object
    pos: int


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object
    pos: int


@dataclass(frozen=True)
class Compare:
    op: str
    left: object
    right: object
    pos: int


@dataclass(frozen=True)
class InList:
    operand: object
    items: tuple
    pos: int


@dataclass(frozen=True)
class Between:
    operand: object
    low: object
    high: object
    pos: int


@dataclass(frozen=True)
class BoolOp:
    op: str          # "and" / "or"
    operands: tuple
    pos: int


@dataclass(frozen=True)
class Not:
    operand: object
    pos: int


def walk(node):
    """Yield ``node`` and every node below it."""
    yield node
    if isinstance(node, (Unary, Not)):
        yield from walk(node.operand)
    elif isinstance(node, (Binary, Compare)):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            yield from walk(a)
    elif isinstance(node, InList):
        yield from walk(node.operand)
        for it in node.items:
            yield from walk(it)
    elif isinstance(node, Between):
        yield from walk(node.operand)
        yield from walk(node.low)
        yield from walk(node.high)
    elif isinstance(node, BoolOp):
        for o in node.operands:
            yield from walk(o)


def names_used(node):
    return sorted({n.name for n in walk(node) if isinstance(n, Name)})
