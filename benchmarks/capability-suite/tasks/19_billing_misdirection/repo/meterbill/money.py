"""Exact money arithmetic on Decimal.

Rules (docs/INVOICES.md, "Rounding"):

* Intermediate amounts (a rated quantity, a converted amount) are carried at
  full precision, then quantized to PRECISE (8 places) so that results do not
  depend on the Decimal context.
* An amount that is printed on an invoice is rounded to the currency's minor
  unit with ROUND_HALF_UP unless a rule names another mode.
* Floats are never accepted: a float amount raises TypeError.
"""

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation

from . import currency as _cur
from .errors import CurrencyMismatch

ZERO = Decimal(0)
PRECISE = Decimal("0.00000001")

ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "down": ROUND_DOWN,
    "floor": ROUND_FLOOR,
    "ceiling": ROUND_CEILING,
}


def mode(name):
    """Map a rounding-mode name from a config file to a decimal constant."""
    try:
        return ROUNDING_MODES[name]
    except KeyError:
        raise ValueError(f"unknown rounding mode {name!r}; expected one of {sorted(ROUNDING_MODES)}") from None


def dec(value):
    """Coerce str/int/Decimal to Decimal; reject floats and junk."""
    if isinstance(value, bool):
        raise TypeError("bool is not an amount")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError(f"float amounts are not allowed: {value!r}")
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        try:
            out = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"not a decimal amount: {value!r}") from None
        if not out.is_finite():
            raise ValueError(f"not a finite amount: {value!r}")
        return out
    raise TypeError(f"cannot make an amount from {type(value).__name__}")


def precise(value):
    """Quantize an intermediate amount to PRECISE, half-even."""
    return dec(value).quantize(PRECISE, rounding=ROUND_HALF_EVEN)


def round_to(value, code, rounding="half_up"):
    """Round ``value`` to the minor unit of currency ``code``."""
    rm = rounding if rounding in ROUNDING_MODES.values() else mode(rounding)
    return dec(value).quantize(_cur.get(code).quantum, rounding=rm)


class Money:
    """An amount in one currency.  Immutable; arithmetic keeps full precision."""

    __slots__ = ("amount", "currency")

    def __init__(self, amount, currency):
        object.__setattr__(self, "amount", dec(amount))
        object.__setattr__(self, "currency", _cur.get(currency).code)

    def __setattr__(self, name, value):
        raise AttributeError("Money is immutable")

    @classmethod
    def zero(cls, currency):
        return cls(ZERO, currency)

    def _check(self, other):
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(self.currency, other.currency)

    def __add__(self, other):
        if other == 0:
            return self
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    __radd__ = __add__

    def __sub__(self, other):
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self):
        return Money(-self.amount, self.currency)

    def __mul__(self, factor):
        if isinstance(factor, Money):
            raise TypeError("cannot multiply Money by Money")
        return Money(self.amount * dec(factor), self.currency)

    __rmul__ = __mul__

    def __eq__(self, other):
        if isinstance(other, int) and other == 0:
            return self.amount == 0
        if not isinstance(other, Money):
            return NotImplemented
        return self.currency == other.currency and self.amount == other.amount

    def __hash__(self):
        return hash((self.amount.normalize(), self.currency))

    def __lt__(self, other):
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other):
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other):
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other):
        self._check(other)
        return self.amount >= other.amount

    def __bool__(self):
        return self.amount != 0

    def is_negative(self):
        return self.amount < 0

    def rounded(self, rounding="half_up"):
        """This amount rounded to the currency's minor unit."""
        return Money(round_to(self.amount, self.currency, rounding), self.currency)

    def precise(self):
        return Money(precise(self.amount), self.currency)

    def minor_units(self):
        """Integer count of minor units; the amount must already be rounded."""
        q = _cur.get(self.currency).quantum
        units = self.amount / q
        if units != units.to_integral_value():
            raise ValueError(f"{self!r} is not rounded to the minor unit")
        return int(units)

    def __repr__(self):
        return f"Money('{self.amount}', '{self.currency}')"

    def __str__(self):
        return f"{self.amount} {self.currency}"


def money_sum(items, currency):
    """Exact sum of Money values (all of ``currency``); empty sum is zero."""
    total = Money.zero(currency)
    for m in items:
        total = total + m
    return total


def _weight(w):
    """A share weight as a Decimal; only the ratios between weights matter."""
    return dec(w).to_integral_value(rounding=ROUND_DOWN)


def allocate(total, weights):
    """Split a rounded Money ``total`` over ``weights`` in minor units.

    Largest-remainder method: every part is the floor of its exact share, and
    the minor units left over go to the parts with the largest remainders
    (ties: earlier part first).  Parts always sum exactly to ``total``.
    """
    weights = [_weight(w) for w in weights]
    if not weights:
        raise ValueError("allocate() needs at least one weight")
    if any(w < 0 for w in weights):
        raise ValueError("negative weight")
    whole = sum(weights, ZERO)
    units = total.minor_units()
    if whole == 0:
        raise ValueError("all weights are zero")
    sign = -1 if units < 0 else 1
    units = abs(units)
    exact = [Decimal(units) * w / whole for w in weights]
    floors = [int(e) for e in exact]
    left = units - sum(floors)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    q = _cur.get(total.currency).quantum
    return [Money(sign * Decimal(f) * q, total.currency) for f in floors]
