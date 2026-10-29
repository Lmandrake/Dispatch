"""Offset pagination for list endpoints.

Query parameters: ``limit`` (default 25, 1-100) and ``cursor`` (the opaque
offset a previous page returned as ``next_cursor``).  A malformed value is a
``BadRequest`` which the router turns into a 400.
"""

from dataclasses import dataclass

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


class BadRequest(ValueError):
    """A client error: the router answers 400 with the message."""


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    limit: int
    offset: int
    next_cursor: object = None   # str or None

    def to_dict(self, key="items"):
        return {key: self.items, "total": self.total, "limit": self.limit,
                "next_cursor": self.next_cursor}


def _int_param(query, name, default, lo, hi):
    raw = query.get(name)
    if raw is None or raw == "":
        return default
    text = str(raw)
    if not text.isascii() or not text.isdigit():
        raise BadRequest(f"{name} must be a whole number, got {text!r}")
    value = int(text)
    if not lo <= value <= hi:
        raise BadRequest(f"{name} must be between {lo} and {hi}")
    return value


def paginate(items, query):
    """The Page of ``items`` selected by ``query`` (a dict of str)."""
    limit = _int_param(query, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int_param(query, "cursor", 0, 0, 10 ** 9)
    items = list(items)
    if offset > len(items):
        raise BadRequest("cursor is past the end of the list")
    chunk = items[offset: offset + limit]
    more = offset + limit < len(items)
    return Page(chunk, len(items), limit, offset, str(offset + limit) if more else None)
