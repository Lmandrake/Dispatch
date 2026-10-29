"""Rating: turn a billed quantity into an amount, per docs/PRICING.md.

Pricing models
--------------

``per_unit``   quantity * unit_price.

``graduated``  the quantity is split over the tiers; each slice is priced at
               its own tier's unit price.  A tier's ``flat_fee`` is charged
               once if any of the quantity falls in it.

``volume``     the whole quantity is priced at the unit price of the single
               tier it falls in, plus that tier's ``flat_fee``.

``package``    a price per block of ``package_size`` units; a partial block is
               charged as a full one.  ``included`` units are free first.

``flat``       ``unit_price`` once, whatever the quantity (0 or more).

Every model honours ``included``: that many units are subtracted first (never
below zero) before pricing.  Amounts are returned at PRECISE precision in the
charge's currency; rounding to the currency happens on the invoice.
"""

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from .errors import ConfigError
from .money import ZERO, dec, precise

INF = None  # an open-ended tier has up_to None
MODELS = ("per_unit", "graduated", "volume", "package", "flat")


@dataclass(frozen=True)
class Tier:
    up_to: Decimal | None
    unit_price: Decimal
    flat_fee: Decimal = ZERO

    def label(self, lower):
        if self.up_to is None:
            return f"above {fmt_qty(lower)}"
        return f"{fmt_qty(lower + 1 if lower == lower.to_integral_value() else lower)}-{fmt_qty(self.up_to)}"


@dataclass(frozen=True)
class PriceSpec:
    model: str
    unit_price: Decimal = ZERO
    tiers: tuple = ()
    package_size: Decimal = Decimal(1)
    included: Decimal = ZERO


@dataclass(frozen=True)
class RatedSlice:
    label: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class Rating:
    quantity: Decimal          # billed quantity before the allowance
    chargeable: Decimal        # after ``included`` was taken off
    amount: Decimal            # PRECISE
    slices: tuple = field(default_factory=tuple)


def fmt_qty(q):
    """Compact quantity text for tier labels: 1000000 -> '1,000,000'."""
    q = dec(q)
    if q == q.to_integral_value():
        return f"{int(q):,}"
    return f"{q.normalize():,f}"


def parse_tiers(raw, where):
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: tiers must be a non-empty list")
    tiers = []
    last = None
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            raise ConfigError(f"{where}: tier {i + 1} must be a table")
        up = t.get("up_to", "inf")
        if up in ("inf", None):
            up_to = None
            if i != len(raw) - 1:
                raise ConfigError(f"{where}: only the last tier may be open-ended")
        else:
            up_to = dec(str(up))
            if up_to <= 0:
                raise ConfigError(f"{where}: tier {i + 1} up_to must be positive")
            if last is not None and up_to <= last:
                raise ConfigError(f"{where}: tier bounds must increase")
            last = up_to
        if "unit_price" not in t:
            raise ConfigError(f"{where}: tier {i + 1} needs unit_price")
        tiers.append(Tier(up_to, dec(str(t["unit_price"])), dec(str(t.get("flat_fee", "0")))))
    if tiers[-1].up_to is not None:
        raise ConfigError(f"{where}: the last tier must be open-ended (up_to = \"inf\")")
    return tuple(tiers)


def parse_price(raw, where):
    model = raw.get("model", "per_unit")
    if model not in MODELS:
        raise ConfigError(f"{where}: unknown pricing model {model!r}")
    included = dec(str(raw.get("included", "0")))
    if included < 0:
        raise ConfigError(f"{where}: included must not be negative")
    if model in ("graduated", "volume"):
        return PriceSpec(model, tiers=parse_tiers(raw.get("tiers"), where), included=included)
    if "unit_price" not in raw:
        raise ConfigError(f"{where}: {model} pricing needs unit_price")
    unit_price = dec(str(raw["unit_price"]))
    if unit_price < 0:
        raise ConfigError(f"{where}: unit_price must not be negative")
    if model == "package":
        size = dec(str(raw.get("package_size", "0")))
        if size <= 0:
            raise ConfigError(f"{where}: package_size must be positive")
        return PriceSpec(model, unit_price=unit_price, package_size=size, included=included)
    return PriceSpec(model, unit_price=unit_price, included=included)


def tier_for(tiers, quantity):
    """Index of the tier a quantity falls in."""
    for i, tier in enumerate(tiers):
        if tier.up_to is None or quantity < tier.up_to:
            return i
    return len(tiers) - 1


def _rate_graduated(tiers, q):
    slices = []
    total = ZERO
    lower = ZERO
    for tier in tiers:
        if q <= lower:
            break
        top = q if tier.up_to is None else min(q, tier.up_to)
        portion = top - lower
        amount = portion * tier.unit_price + tier.flat_fee
        slices.append(RatedSlice(tier.label(lower), portion, tier.unit_price, amount))
        total += amount
        if tier.up_to is None:
            break
        lower = tier.up_to
    return total, slices


def _rate_volume(tiers, q):
    if q == 0:
        return ZERO, []
    i = tier_for(tiers, q)
    tier = tiers[i]
    lower = ZERO if i == 0 else tiers[i - 1].up_to
    amount = q * tier.unit_price + tier.flat_fee
    return amount, [RatedSlice(tier.label(lower), q, tier.unit_price, amount)]


def rate(spec, quantity):
    """Rate ``quantity`` under ``spec``; returns a Rating."""
    q = dec(quantity)
    if q < 0:
        raise ValueError(f"negative quantity {q}")
    chargeable = max(q - spec.included, ZERO)
    if spec.model == "per_unit":
        amount = chargeable * spec.unit_price
        slices = [RatedSlice("", chargeable, spec.unit_price, amount)] if chargeable else []
    elif spec.model == "graduated":
        amount, slices = _rate_graduated(spec.tiers, chargeable)
    elif spec.model == "volume":
        amount, slices = _rate_volume(spec.tiers, chargeable)
    elif spec.model == "package":
        packs = (chargeable / spec.package_size).to_integral_value(rounding=ROUND_CEILING)
        amount = packs * spec.unit_price
        slices = [RatedSlice(f"{fmt_qty(packs)} x {fmt_qty(spec.package_size)}", packs, spec.unit_price, amount)] if packs else []
    elif spec.model == "flat":
        amount = spec.unit_price
        slices = [RatedSlice("flat", Decimal(1), spec.unit_price, amount)]
    else:  # pragma: no cover - parse_price rejects it
        raise ConfigError(f"unknown model {spec.model}")
    return Rating(q, chargeable, precise(amount), tuple(
        RatedSlice(s.label, s.quantity, s.unit_price, precise(s.amount)) for s in slices))
