"""Locale-aware parsing of amount strings into Decimal.

Accepted shapes (``.`` and ``,`` stand for the locale's decimal mark and group
separator; see ``locales.py``):

    1234.56      1,234.56      -1,234.56     +12
    (1,234.56)   accounting negative
    1,234.56-    trailing minus (bank exports)
    .5           leading decimal mark

Rules:

* grouping is optional, but when present every group after the first must
  have exactly three digits and the first group one to three;
* at most one sign, given by ``-``/``+`` prefix, trailing ``-`` or parentheses;
* any number of fraction digits is kept exactly; nothing is rounded here.

``parse_amount`` never returns a float and never rounds.
"""

from decimal import Decimal, InvalidOperation

from .errors import AmountError
from .locales import get_locale

_MINUS_SIGNS = ("-", "−", "–")


def parse_amount(text, locale=None, *, line=None, source=None):
    """Parse ``text`` in ``locale`` and return a Decimal."""
    spec = get_locale(locale)
    s = text.strip()
    if not s:
        raise AmountError("empty amount", line=line, source=source)

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    if s and s[-1] in _MINUS_SIGNS:
        if negative:
            raise AmountError(f"two signs in {text!r}", line=line, source=source)
        negative = True
        s = s[:-1].rstrip()
    if s and (s[0] in _MINUS_SIGNS or s[0] == "+"):
        if s[0] != "+":
            if negative:
                raise AmountError(f"two signs in {text!r}", line=line, source=source)
            negative = True
        s = s[1:].lstrip()
    if not s:
        raise AmountError(f"no digits in {text!r}", line=line, source=source)

    whole, frac = _split_decimal(s, spec, text, line, source)
    digits = _ungroup(whole, spec, text, line, source)
    if frac and not frac.isdigit():
        raise AmountError(f"bad fraction in {text!r}", line=line, source=source)
    if not digits and not frac:
        raise AmountError(f"no digits in {text!r}", line=line, source=source)
    literal = (digits or "0") + ("." + frac if frac else "")
    try:
        value = Decimal(literal)
    except InvalidOperation:
        raise AmountError(f"bad amount {text!r}", line=line, source=source) from None
    return -value if negative else value


def _split_decimal(s, spec, text, line, source):
    if spec.decimal in s:
        if s.count(spec.decimal) > 1:
            raise AmountError(f"two decimal marks in {text!r}", line=line, source=source)
        whole, frac = s.split(spec.decimal)
        return whole, frac
    return s, ""


def _ungroup(whole, spec, text, line, source):
    if whole.isdigit() or whole == "":
        return whole
    seps = [ch for ch in whole if not ch.isdigit()]
    if not seps:
        return whole
    sep = seps[0]
    if not spec.accepts_group(sep) or any(ch != sep for ch in seps):
        raise AmountError(f"unexpected character in {text!r} for locale {spec.name}",
                          line=line, source=source)
    groups = whole.split(sep)
    if not (1 <= len(groups[0]) <= 3) or any(len(g) != 3 for g in groups[1:]):
        raise AmountError(f"bad digit grouping in {text!r}", line=line, source=source)
    if not all(g.isdigit() for g in groups):
        raise AmountError(f"bad digit grouping in {text!r}", line=line, source=source)
    return "".join(groups)


def parse_c_decimal(text, *, line=None, source=None, what="number"):
    """Parse a plain "C"-convention decimal (rates, shares, directive args)."""
    s = text.strip()
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise AmountError(f"bad {what} {text!r}", line=line, source=source) from None
    if not value.is_finite():
        raise AmountError(f"bad {what} {text!r}", line=line, source=source)
    return value
