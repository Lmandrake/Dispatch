"""Prices are stored as integer cents; these helpers convert to and from text."""

import re

from stockroom.errors import ValidationError

_PRICE_RE = re.compile(r"^\$?(\d{1,9})(?:\.(\d{1,2}))?$")


def parse_price(text):
    """Parse ``"12"``, ``"12.5"``, ``"12.50"`` or ``"$12.50"`` into cents.

    Negative values, more than two decimals and anything else raise
    ValidationError.
    """
    if isinstance(text, int) and not isinstance(text, bool):
        if text < 0:
            raise ValidationError(f"price must not be negative: {text}")
        return text * 100
    s = str(text).strip()
    m = _PRICE_RE.match(s)
    if not m:
        raise ValidationError(f"invalid price: {text!r}")
    whole, frac = m.group(1), m.group(2) or ""
    return int(whole) * 100 + int(frac.ljust(2, "0") or "0")


def format_price(cents):
    """Format cents as ``"12.50"`` (no currency sign, always two decimals)."""
    if cents < 0:
        return "-" + format_price(-cents)
    return f"{cents // 100}.{cents % 100:02d}"
