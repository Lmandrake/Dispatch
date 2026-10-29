"""Coupons (data/coupons.toml) and their redemptions (data/redemptions.csv).

    [coupons.WELCOME10]
    percent_off = "10"          # or amount_off = "50.00" with currency = "USD"
    applies_to = "all"          # all | base | usage
    duration = "repeating"      # once | repeating | forever
    cycles = 3                  # for repeating: how many cycles from the first

    redemptions.csv: customer,coupon,first_cycle

Rules (docs/DISCOUNTS.md):

* A coupon is active for a customer in cycles first_cycle .. first_cycle +
  cycles - 1 (``once``: only first_cycle; ``forever``: from first_cycle on).
* Percent coupons are applied before fixed-amount coupons.  A percent
  coupon takes ``percent_off`` percent of the subtotal of the lines it
  applies to, rounded half-up to the invoice currency.
* A fixed-amount coupon is converted to the invoice currency (rate of the
  period's last day) and rounded half-up.
* The discounts are applied in that order and the running total is capped:
  no coupon can take the discount above the invoice subtotal.
"""

import tomllib
from dataclasses import dataclass
from decimal import Decimal

from . import currency as _cur
from .csvutil import read_rows
from .errors import ConfigError, UnknownCustomer
from .money import ZERO, Money, dec, round_to
from .periods import cycles_between, parse_cycle

APPLIES = ("all", "base", "usage")
DURATIONS = ("once", "repeating", "forever")


@dataclass(frozen=True)
class Coupon:
    code: str
    percent_off: Decimal | None = None
    amount_off: Decimal | None = None
    currency: str | None = None
    applies_to: str = "all"
    duration: str = "once"
    cycles: int = 1
    name: str = ""

    @property
    def is_percent(self):
        return self.percent_off is not None

    def describe(self):
        if self.is_percent:
            pct = self.percent_off.normalize()
            what = "" if self.applies_to == "all" else f" {self.applies_to}"
            return f"{self.name or self.code} ({pct:f}% off{what})"
        return f"{self.name or self.code} ({self.amount_off} {self.currency} off)"

    def active_in(self, first_cycle, cycle):
        n = cycles_between(first_cycle, cycle)
        if n < 0:
            return False
        if self.duration == "once":
            return n == 0
        if self.duration == "repeating":
            return n < self.cycles
        return True


@dataclass(frozen=True)
class Redemption:
    customer: str
    coupon: str
    first_cycle: str


@dataclass(frozen=True)
class AppliedDiscount:
    coupon: Coupon
    amount: Money      # rounded, invoice currency, positive
    basis: Money       # what it was computed from (percent) or converted face value


def parse_coupons(text, *, source="coupons.toml"):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}", source=source) from None
    out = {}
    for code, spec in data.get("coupons", {}).items():
        where = f"coupon {code}"
        pct = spec.get("percent_off")
        amt = spec.get("amount_off")
        if (pct is None) == (amt is None):
            raise ConfigError(f"{where}: exactly one of percent_off / amount_off", source=source)
        applies = spec.get("applies_to", "all")
        if applies not in APPLIES:
            raise ConfigError(f"{where}: applies_to must be one of {', '.join(APPLIES)}", source=source)
        duration = spec.get("duration", "once")
        if duration not in DURATIONS:
            raise ConfigError(f"{where}: duration must be one of {', '.join(DURATIONS)}", source=source)
        cycles = int(spec.get("cycles", 1))
        if duration == "repeating" and cycles < 1:
            raise ConfigError(f"{where}: repeating coupons need cycles >= 1", source=source)
        if pct is not None:
            p = dec(str(pct))
            if not ZERO < p <= 100:
                raise ConfigError(f"{where}: percent_off must be in (0, 100]", source=source)
            out[code] = Coupon(code, percent_off=p, applies_to=applies, duration=duration,
                               cycles=cycles, name=str(spec.get("name", "")))
        else:
            if "currency" not in spec:
                raise ConfigError(f"{where}: amount_off needs a currency", source=source)
            if applies != "all":
                raise ConfigError(f"{where}: fixed-amount coupons apply to the whole invoice", source=source)
            a = dec(str(amt))
            if a <= 0:
                raise ConfigError(f"{where}: amount_off must be positive", source=source)
            out[code] = Coupon(code, amount_off=a, currency=_cur.get(spec["currency"]).code,
                               duration=duration, cycles=cycles, name=str(spec.get("name", "")))
    return out


def parse_redemptions(text, *, coupons, customers=None, source="redemptions.csv"):
    out = []
    for lineno, r in read_rows(text, required=("customer", "coupon", "first_cycle"), source=source):
        cid = r["customer"].upper()
        if customers is not None and cid not in customers:
            raise UnknownCustomer(f"{source} line {lineno}: unknown customer {cid}")
        if r["coupon"] not in coupons:
            raise ConfigError(f"line {lineno}: unknown coupon {r['coupon']!r}", source=source)
        parse_cycle(r["first_cycle"])
        out.append(Redemption(cid, r["coupon"], r["first_cycle"]))
    return out


def active_coupons(coupons, redemptions, cid, cycle):
    """Coupons active for ``cid`` in ``cycle``: percent ones first, then by code."""
    found = {}
    for red in redemptions:
        if red.customer != cid:
            continue
        c = coupons[red.coupon]
        if c.active_in(red.first_cycle, cycle):
            found[c.code] = c
    return sorted(found.values(), key=lambda c: (not c.is_percent, c.code))


def apply_coupons(coupons, lines, subtotal, converter, on):
    """Discounts for an invoice.

    ``lines``: the invoice's (kind, Money) pairs, kind "base" | "usage" | "fee".
    Returns a list of AppliedDiscount; their sum never exceeds ``subtotal``.
    """
    cur = subtotal.currency
    applied = []
    running = Money.zero(cur)
    for c in coupons:
        if c.is_percent:
            basis = Money.zero(cur)
            for kind, amount in lines:
                if kind == "fee":
                    continue
                if c.applies_to == "all" or c.applies_to == kind:
                    basis = basis + amount
            raw = basis.amount * c.percent_off / 100
            amount = Money(round_to(raw, cur), cur)
        else:
            face = converter.convert(Money(c.amount_off, c.currency), cur, on)
            basis = face
            amount = Money(round_to(face.amount, cur), cur)
        room = subtotal - running
        if amount > room:
            amount = room
        if not amount:
            continue
        running = running + amount
        applied.append(AppliedDiscount(c, amount, basis))
    return applied


def total_discount(applied, currency):
    total = Money.zero(currency)
    for a in applied:
        total = total + a.amount
    return total
