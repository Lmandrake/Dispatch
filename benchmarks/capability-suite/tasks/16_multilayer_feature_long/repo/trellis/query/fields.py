"""Fields the query language can look at.

Each field has a *type* that decides which operators it accepts and how the
right-hand value is parsed and compared.  The table is the reference; the
user guide (docs/QUERY.md) explains the same rules with examples.

=======  ==========================  ==========================================
type     operators                   values and comparison
=======  ==========================  ==========================================
text     = != ~ in                   any text; every comparison is
                                     case-insensitive; ~ is a substring test
enum     = != in, and < <= > >= for  one of the field's choices (an unknown
         ordered enums (priority)    choice is a QueryError); ordered enums
                                     compare by rank (low < normal < ...)
int      = != < <= > >= in           an integer; ``none`` matches no value
date     = != < <= > >= in           YYYY-MM-DD or a relative date (today,
                                     +3d, -1w, +1m, ...); ``none`` matches no
                                     date.  An issue with no date never
                                     satisfies = < <= > >= or in, and always
                                     satisfies != (except ``!= none``)
user     = != in                     a username, or ``me`` (the acting user);
                                     ``none`` matches no user; case-insensitive
list     = != ~ in                   multi-valued (labels, watchers):
                                     ``= X`` has X, ``!= X`` lacks X,
                                     ``in (X, Y)`` has at least one,
                                     ``~ X`` some value contains X
bool     (bare) or = !=              true/false/yes/no/1/0
=======  ==========================  ==========================================

Getters receive the issue and an ``EvalContext`` (today's date, the acting
user) and return the raw value; the compiler does the comparing.
"""

from dataclasses import dataclass
from typing import Callable

from trellis.dates import resolve_date
from trellis.errors import QueryError, ValidationError
from trellis.models import PRIORITIES, STATUSES, TYPES


@dataclass(frozen=True)
class EvalContext:
    today: str
    me: str = ""


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    getter: Callable
    choices: tuple = ()
    ordered: bool = False
    #: True when the field's value depends on the EvalContext (today / me)
    contextual: bool = False


def _overdue(issue, ctx):
    return bool(issue.due) and issue.is_open and issue.due < ctx.today


FIELDS = {
    "key": Field("key", "text", lambda i, c: i.key),
    "project": Field("project", "text", lambda i, c: i.project),
    "number": Field("number", "int", lambda i, c: i.number),
    "title": Field("title", "text", lambda i, c: i.title),
    "description": Field("description", "text", lambda i, c: i.description),
    "type": Field("type", "enum", lambda i, c: i.type, choices=TYPES),
    "status": Field("status", "enum", lambda i, c: i.status, choices=STATUSES),
    "priority": Field("priority", "enum", lambda i, c: i.priority, choices=PRIORITIES, ordered=True),
    "assignee": Field("assignee", "user", lambda i, c: i.assignee),
    "reporter": Field("reporter", "user", lambda i, c: i.reporter),
    "label": Field("label", "list", lambda i, c: i.labels),
    "watcher": Field("watcher", "list", lambda i, c: i.watchers),
    "due": Field("due", "date", lambda i, c: i.due),
    "created": Field("created", "date", lambda i, c: i.created_at[:10]),
    "updated": Field("updated", "date", lambda i, c: i.updated_at[:10]),
    "closed": Field("closed", "date", lambda i, c: i.closed_at[:10]),
    "estimate": Field("estimate", "int", lambda i, c: i.estimate),
    "open": Field("open", "bool", lambda i, c: i.is_open),
    "overdue": Field("overdue", "bool", _overdue, contextual=True),
    "unassigned": Field("unassigned", "bool", lambda i, c: not i.assignee),
    "mine": Field("mine", "bool", lambda i, c: bool(c.me) and i.assignee == c.me, contextual=True),
}

ALIASES = {
    "labels": "label",
    "tag": "label",
    "watchers": "watcher",
    "pri": "priority",
    "who": "assignee",
    "est": "estimate",
    "deadline": "due",
}

OPERATORS_BY_TYPE = {
    "text": ("=", "!=", "~", "in"),
    "enum": ("=", "!=", "in"),
    "ordered_enum": ("=", "!=", "<", "<=", ">", ">=", "in"),
    "int": ("=", "!=", "<", "<=", ">", ">=", "in"),
    "date": ("=", "!=", "<", "<=", ">", ">=", "in"),
    "user": ("=", "!=", "in"),
    "list": ("=", "!=", "~", "in"),
    "bool": ("=", "!="),
}

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}
NONE_WORDS = {"none", "null", "empty"}


def lookup(name, pos):
    key = name.lower()
    key = ALIASES.get(key, key)
    field = FIELDS.get(key)
    if field is None:
        known = ", ".join(sorted(FIELDS))
        raise QueryError(f"unknown field {name!r}; known fields: {known}", pos)
    return field


def operators_for(field):
    if field.type == "enum" and field.ordered:
        return OPERATORS_BY_TYPE["ordered_enum"]
    return OPERATORS_BY_TYPE[field.type]


def check_operator(field, op, pos):
    allowed = operators_for(field)
    if op not in allowed:
        raise QueryError(
            f"operator {op} does not apply to {field.name} ({field.type}); use one of {' '.join(allowed)}",
            pos,
        )


def convert(field, raw, pos, ctx):
    """Turn raw right-hand text into a value comparable with the field's
    getter output.  ``None`` stands for "no value" (``none``)."""
    t = field.type
    low = raw.strip().lower()
    if t == "text":
        return low
    if t == "enum":
        value = low.replace("-", "_")
        if value not in field.choices:
            raise QueryError(f"{field.name} must be one of {', '.join(field.choices)}, got {raw!r}", pos)
        return value
    if t == "int":
        if low in NONE_WORDS:
            return None
        try:
            return int(raw)
        except ValueError:
            raise QueryError(f"{field.name} needs an integer, got {raw!r}", pos) from None
    if t == "date":
        if low in NONE_WORDS:
            return None
        try:
            return resolve_date(raw, ctx.today)
        except ValidationError:
            raise QueryError(f"{field.name} needs a date (YYYY-MM-DD, today, +3d, ...), got {raw!r}",
                             pos) from None
    if t == "user":
        if low in NONE_WORDS:
            return None
        if low == "me":
            return ctx.me
        return low
    if t == "list":
        return low
    if t == "bool":
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise QueryError(f"{field.name} needs true or false, got {raw!r}", pos)
    raise AssertionError(t)
