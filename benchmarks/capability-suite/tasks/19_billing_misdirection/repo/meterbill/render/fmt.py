"""Number formatting shared by the renderers.

``format_amount`` prints an amount that is already rounded to the minor unit
of its currency.  It re-quantizes to the currency exponent only to fix the
number of printed digits (Decimal('12.5') -> '12.50'); since every amount
it is given is already rounded, this never changes a value.  If it ever
would, that is a bug upstream, and ``strict=True`` turns it into an error.
"""

from decimal import ROUND_HALF_UP, Decimal

from .. import currency as _cur


class UnroundedAmount(ValueError):
    pass


def format_amount(money, *, grouping=True, strict=False):
    """'1,234.50' for Money('1234.5', 'USD'); '-' prefix for negatives."""
    cur = _cur.get(money.currency)
    q = cur.quantum
    value = money.amount.quantize(q, rounding=ROUND_HALF_UP)
    if strict and value != money.amount:
        raise UnroundedAmount(f"{money!r} is not rounded to {q}")
    sign = "-" if value < 0 else ""
    value = abs(value)
    if cur.exponent == 0:
        whole, frac = f"{int(value)}", ""
    else:
        text = f"{value:f}"
        whole, _, frac = text.partition(".")
    if grouping:
        whole = f"{int(whole):,}"
    return f"{sign}{whole}.{frac}" if frac else f"{sign}{whole}"


def format_money(money, **kw):
    """Amount with its currency code: '1,234.50 USD'."""
    return f"{format_amount(money, **kw)} {money.currency}"


def plain_amount(money):
    """Machine form: no grouping, fixed digits: '-1234.50'."""
    return format_amount(money, grouping=False)


def format_qty(q, precision=0):
    """Quantity with the metric's display precision and grouping."""
    q = Decimal(q)
    if precision == 0 and q != q.to_integral_value():
        # a fractional quantity of an integral metric: show what we have
        text = f"{q.normalize():,f}"
        return text
    shown = q.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
    return f"{shown:,.{precision}f}"


def format_unit_price(p):
    """Unit prices keep their significant digits: 0.00042 stays 0.00042."""
    p = Decimal(p).normalize()
    if p == p.to_integral_value():
        return f"{int(p):,}.00"
    text = f"{p:f}"
    whole, _, frac = text.partition(".")
    if len(frac) < 2:
        frac = frac.ljust(2, "0")
    return f"{int(whole):,}.{frac}"


def format_rate(rate_text):
    return rate_text


def pad(text, width, align="<"):
    if align == ">":
        return text.rjust(width)
    return text.ljust(width)
