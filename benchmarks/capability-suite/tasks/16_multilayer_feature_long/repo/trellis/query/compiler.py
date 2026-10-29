"""Turn a parsed query into a predicate ``issue -> bool``.

Compiling resolves every value once (relative dates against ``today``,
``me`` against the acting user), so the predicate itself is cheap.
Compiled predicates are memoised by ``(text, today, me)``: the same query
text can mean different things on different days or for different users,
so all three are part of the cache key.
"""

from functools import lru_cache

from trellis.dates import is_date
from trellis.errors import QueryError
from trellis.models import priority_rank
from trellis.query import fields as F
from trellis.query.ast import And, Compare, Flag, Not, Or
from trellis.query.parser import parse


def _match_all(issue):
    return True


def _cmp(op, left, right):
    if op == "=":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise AssertionError(op)


def _compile_compare(node, ctx):
    field = F.FIELDS[node.field]
    values = [F.convert(field, v, node.pos, ctx) for v in node.values]
    get = field.getter
    op = node.op
    t = field.type

    if t == "list":
        if op == "=":
            v = values[0]
            return lambda i: v in get(i, ctx)
        if op == "!=":
            v = values[0]
            return lambda i: v not in get(i, ctx)
        if op == "in":
            vs = set(values)
            return lambda i: any(x in vs for x in get(i, ctx))
        if op == "~":
            v = values[0]
            return lambda i: any(v in x for x in get(i, ctx))
        raise AssertionError(op)

    if t == "text":
        if op == "~":
            v = values[0]
            return lambda i: v in get(i, ctx).lower()
        if op == "in":
            vs = set(values)
            return lambda i: get(i, ctx).lower() in vs
        v = values[0]
        return lambda i: _cmp(op, get(i, ctx).lower(), v)

    if t == "enum":
        if op == "in":
            vs = set(values)
            return lambda i: get(i, ctx) in vs
        if field.ordered and op not in ("=", "!="):
            r = priority_rank(values[0])
            return lambda i: _cmp(op, priority_rank(get(i, ctx)), r)
        v = values[0]
        return lambda i: _cmp(op, get(i, ctx), v)

    if t == "user":
        def norm(i):
            return get(i, ctx) or None
        if op == "in":
            vs = set(values)
            return lambda i: norm(i) in vs
        v = values[0]
        return lambda i: _cmp(op, norm(i), v)

    if t in ("int", "date"):
        empty = (lambda x: x is None) if t == "int" else (lambda x: not x)
        if op == "in":
            vs = {v for v in values if v is not None}
            want_none = any(v is None for v in values)
            return lambda i: (want_none if empty(get(i, ctx)) else get(i, ctx) in vs)
        v = values[0]
        if v is None:
            if op == "=":
                return lambda i: empty(get(i, ctx))
            if op == "!=":
                return lambda i: not empty(get(i, ctx))
            raise QueryError(f"none can only be compared with = or != ({field.name})", node.pos)
        if op == "!=":
            return lambda i: empty(get(i, ctx)) or get(i, ctx) != v
        return lambda i: (not empty(get(i, ctx))) and _cmp(op, get(i, ctx), v)

    if t == "bool":
        v = values[0]
        if op == "=":
            return lambda i: bool(get(i, ctx)) == v
        return lambda i: bool(get(i, ctx)) != v

    raise AssertionError(t)


def _compile(node, ctx):
    if node is None:
        return _match_all
    if isinstance(node, Flag):
        field = F.FIELDS[node.field]
        get = field.getter
        return lambda i: bool(get(i, ctx))
    if isinstance(node, Compare):
        return _compile_compare(node, ctx)
    if isinstance(node, Not):
        inner = _compile(node.operand, ctx)
        return lambda i: not inner(i)
    if isinstance(node, And):
        a, b = _compile(node.left, ctx), _compile(node.right, ctx)
        return lambda i: a(i) and b(i)
    if isinstance(node, Or):
        a, b = _compile(node.left, ctx), _compile(node.right, ctx)
        return lambda i: a(i) or b(i)
    raise TypeError(node)


@lru_cache(maxsize=256)
def _compiled(text, today, me):
    return _compile(parse(text), F.EvalContext(today=today, me=me))


def compile_query(text, today, me=""):
    """A predicate for ``text``.  ``today`` is a YYYY-MM-DD string."""
    if not is_date(today):
        raise QueryError(f"bad evaluation date {today!r}")
    return _compiled(text or "", today, me or "")


def filter_issues(issues, text, today, me=""):
    pred = compile_query(text, today, me)
    return [i for i in issues if pred(i)]
