"""Decimal helpers shared by every stage.

Two precisions exist in ledgerkit:

* MICRO (six decimal places) is the working precision of every converted or
  allocated amount.  Stages upstream of the report quantize to MICRO with
  ROUND_HALF_EVEN and never to anything coarser.
* CENT is display precision.  Only the report layer rounds to cents, with
  ROUND_HALF_UP (half a cent rounds away from zero), which is what our
  accountants expect to see on paper.
"""

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

ZERO = Decimal("0")
MICRO = Decimal("0.000001")
CENT = Decimal("0.01")

CURRENCY_PLACES = {
    "JPY": 0,
    "KRW": 0,
    "BHD": 3,
    "KWD": 3,
}


def places_for(currency):
    """Number of display decimal places for ``currency`` (default 2)."""
    return CURRENCY_PLACES.get(currency.upper(), 2)


def to_micro(value):
    """Quantize to working precision (six places, half-even)."""
    return Decimal(value).quantize(MICRO, rounding=ROUND_HALF_EVEN)


def round_money(value, places=2):
    """Round ``value`` for display: ``places`` decimals, half away from zero."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def total(values):
    """Exact Decimal sum of an iterable (empty -> 0)."""
    acc = ZERO
    for v in values:
        acc += v
    return acc


def is_zero(value, places=None):
    if places is None:
        return value == 0
    return round_money(value, places) == 0


def group_digits(digits, sep):
    """``"1234567"`` -> ``"1,234,567"`` (sep may be empty)."""
    if not sep or len(digits) <= 3:
        return digits
    head = len(digits) % 3 or 3
    parts = [digits[:head]]
    for i in range(head, len(digits), 3):
        parts.append(digits[i:i + 3])
    return sep.join(parts)
