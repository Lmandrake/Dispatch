"""Fields the query language can look at.

Each field has a type that decides which operators it accepts and how the
right-hand value is parsed:

=========  ==========================  ===============================
type       operators                   value
=========  ==========================  ===============================
str        = != ~ in                   any text; = and != and in are
                                       case-sensitive, ~ is a
                                       case-insensitive substring test
int        = != < <= > >= in           an integer
money      = != < <= > >= in           a price such as 12 or 12.50
bool       (bare) or = !=              true/false/yes/no/1/0
=========  ==========================  ===============================
"""

from dataclasses import dataclass
from typing import Callable

from stockroom.errors import QueryError, ValidationError
from stockroom.money import parse_price


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    getter: Callable


FIELDS = {
    "sku": Field("sku", "str", lambda it: it.sku),
    "name": Field("name", "str", lambda it: it.name),
    "location": Field("location", "str", lambda it: it.location),
    "quantity": Field("quantity", "int", lambda it: it.quantity),
    "reorder_level": Field("reorder_level", "int", lambda it: it.reorder_level),
    "price": Field("price", "money", lambda it: it.price_cents),
    "value": Field("value", "money", lambda it: it.value_cents),
    "low": Field("low", "bool", lambda it: it.is_low),
}

ALIASES = {
    "qty": "quantity",
    "loc": "location",
    "reorder": "reorder_level",
}

OPERATORS_BY_TYPE = {
    "str": ("=", "!=", "~", "in"),
    "int": ("=", "!=", "<", "<=", ">", ">=", "in"),
    "money": ("=", "!=", "<", "<=", ">", ">=", "in"),
    "bool": ("=", "!="),
}

_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}


def lookup(name, pos):
    key = name.lower()
    key = ALIASES.get(key, key)
    field = FIELDS.get(key)
    if field is None:
        known = ", ".join(sorted(FIELDS))
        raise QueryError(f"unknown field {name!r}; known fields: {known}", pos)
    return field


def convert(field, raw, pos):
    """Turn the raw right-hand text into a value comparable with the field."""
    if field.type == "str":
        return raw
    if field.type == "int":
        try:
            return int(raw)
        except ValueError:
            raise QueryError(f"{field.name} needs an integer, got {raw!r}", pos) from None
    if field.type == "money":
        try:
            return parse_price(raw)
        except ValidationError:
            raise QueryError(f"{field.name} needs a price, got {raw!r}", pos) from None
    if field.type == "bool":
        low = raw.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise QueryError(f"{field.name} needs true or false, got {raw!r}", pos)
    raise AssertionError(field.type)
