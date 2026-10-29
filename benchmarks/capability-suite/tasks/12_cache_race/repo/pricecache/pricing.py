"""Pure pricing rules. No I/O, no caching: everything comes in as arguments.

Records (as stored in VersionedStore):

    ("price", sku)     {"base_cents": int, "currency": "USD",
                        "tiers": [[min_qty, discount_bp], ...]}
    ("region", code)   {"currency": "EUR", "tax_bp": int, "markup_bp": int,
                        "rounding": "cent" | "five_cents" | "whole"}
    ("fx", currency)   {"rate": "0.9213"}   units of currency per 1 USD
    ("promo", code)    {"skus": [...] or "*", "discount_bp": int, "active": bool,
                        "min_qty": int}

Request options (all optional):

    gift_wrap: bool          flat GIFT_WRAP_CENTS per order (in USD, converted)
    rush: bool               RUSH_BP surcharge on the merchandise subtotal
    promo: str               promo code; ignored if unknown/inactive/not applicable
    member: bool             MEMBER_BP discount, applied after tiers
    engraving: {"lines": [..]}  ENGRAVING_CENTS_PER_LINE per non-empty line per unit

Order of application, all in Decimal minor units of the base currency (USD):
    base * qty -> tier discount -> member discount -> promo -> rush
    -> + engraving -> + gift wrap -> channel markup -> FX -> region markup
    -> tax -> region rounding
"""

from decimal import Decimal
from typing import Optional

from .records import Quote, apply_basis_points, parse_rate, to_cents

BASE_CURRENCY = "USD"
GIFT_WRAP_CENTS = 499
RUSH_BP = 1500
MEMBER_BP = -500
ENGRAVING_CENTS_PER_LINE = 250

CHANNEL_MARKUP_BP = {
    "web": 0,
    "app": -200,
    "store": 300,
    "partner": 800,
}


class PricingError(ValueError):
    pass


def tier_discount_bp(tiers, qty: int) -> int:
    """The discount of the highest tier whose min_qty <= qty (0 if none)."""
    best_min, best_bp = 0, 0
    for min_qty, bp in tiers or ():
        if min_qty <= qty and min_qty >= best_min:
            best_min, best_bp = min_qty, bp
    return best_bp


def promo_applies(promo: Optional[dict], sku: str, qty: int) -> bool:
    if not promo or not promo.get("active", False):
        return False
    skus = promo.get("skus", "*")
    if skus != "*" and sku not in skus:
        return False
    return qty >= int(promo.get("min_qty", 1))


def engraving_lines(spec) -> int:
    if not spec:
        return 0
    lines = spec.get("lines", []) if isinstance(spec, dict) else spec
    return sum(1 for line in lines if str(line).strip())


def round_for_region(cents: int, rounding: str) -> int:
    if rounding in (None, "cent"):
        return cents
    if rounding == "five_cents":
        return int(Decimal(cents / 5).quantize(Decimal(1)) * 5)
    if rounding == "whole":
        return int(Decimal(cents / 100).quantize(Decimal(1)) * 100)
    raise PricingError(f"unknown rounding rule {rounding!r}")


def compute_quote(
    sku: str,
    region_code: str,
    qty: int,
    channel: str,
    options: dict,
    price_rec,
    region_rec,
    fx_rec,
    promo_rec=None,
) -> Quote:
    """Compute a Quote. ``*_rec`` are store Records (fx_rec may be None for USD)."""
    if qty < 1:
        raise PricingError("qty must be at least 1")
    if price_rec is None or price_rec.deleted:
        raise PricingError(f"no price for {sku}")
    if region_rec is None or region_rec.deleted:
        raise PricingError(f"unknown region {region_code}")
    if channel not in CHANNEL_MARKUP_BP:
        raise PricingError(f"unknown channel {channel!r}")

    price = price_rec.value
    region = region_rec.value
    if price.get("currency", BASE_CURRENCY) != BASE_CURRENCY:
        raise PricingError("base prices must be in USD")

    applied = []
    amount = Decimal(int(price["base_cents"])) * qty

    bp = tier_discount_bp(price.get("tiers"), qty)
    if bp:
        amount = apply_basis_points(amount, -abs(bp))
        applied.append(f"tier:{bp}")

    if options.get("member"):
        amount = apply_basis_points(amount, MEMBER_BP)
        applied.append("member")

    promo_code = options.get("promo")
    if promo_code and promo_rec is not None and not promo_rec.deleted:
        if promo_applies(promo_rec.value, sku, qty):
            amount = apply_basis_points(amount, -abs(int(promo_rec.value["discount_bp"])))
            applied.append(f"promo:{str(promo_code).upper()}")

    if options.get("rush"):
        amount = apply_basis_points(amount, RUSH_BP)
        applied.append("rush")

    lines = engraving_lines(options.get("engraving"))
    if lines:
        amount += Decimal(ENGRAVING_CENTS_PER_LINE * lines * qty)
        applied.append(f"engraving:{lines}")

    if options.get("gift_wrap"):
        amount += Decimal(GIFT_WRAP_CENTS)
        applied.append("gift_wrap")

    amount = apply_basis_points(amount, CHANNEL_MARKUP_BP[channel])

    currency = region.get("currency", BASE_CURRENCY)
    fx_version = 0
    if currency != BASE_CURRENCY:
        if fx_rec is None or fx_rec.deleted:
            raise PricingError(f"no FX rate for {currency}")
        amount = amount * parse_rate(fx_rec.value["rate"])
        fx_version = fx_rec.version

    amount = apply_basis_points(amount, int(region.get("markup_bp", 0)))
    amount = apply_basis_points(amount, int(region.get("tax_bp", 0)))

    total = round_for_region(to_cents(amount), region.get("rounding", "cent"))
    unit = to_cents(Decimal(total) / qty)
    return Quote(
        sku=sku,
        region=region_code,
        currency=currency,
        channel=channel,
        qty=qty,
        unit_cents=unit,
        total_cents=total,
        price_version=price_rec.version,
        fx_version=fx_version,
        applied=tuple(applied),
    )
