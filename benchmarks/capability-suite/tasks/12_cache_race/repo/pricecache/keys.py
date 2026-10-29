"""Cache key construction.

Cache keys must be hashable and must compare equal exactly when two calls
would compute the same result. Option dicts come straight from request JSON,
so their key order is arbitrary and their values may be nested dicts/lists.
"""

from collections import namedtuple

QuoteKey = namedtuple("QuoteKey", "sku region qty channel options")


def freeze(value):
    """Turn a JSON-like value into something hashable.

    dicts are order-insensitive (the same options in a different order share
    a cache entry); lists keep their order.
    """
    if isinstance(value, dict):
        return frozenset(freeze(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(freeze(v) for v in value)
    return value


def normalize_region(region: str) -> str:
    return region.strip().upper()


def normalize_channel(channel: str) -> str:
    return channel.strip().lower()


def quote_key(sku, region, qty=1, channel="web", options=None) -> QuoteKey:
    return QuoteKey(
        sku,
        normalize_region(region),
        int(qty),
        normalize_channel(channel),
        freeze(options or {}),
    )


def record_key(kind: str, name: str) -> tuple:
    """Store/record-cache key, e.g. ("price", "SKU-1") or ("region", "DE")."""
    if kind == "region":
        name = normalize_region(name)
    elif kind in ("fx", "promo"):
        name = name.strip().upper()
    return (kind, name)
