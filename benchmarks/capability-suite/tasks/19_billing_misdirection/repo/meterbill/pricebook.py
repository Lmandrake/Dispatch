"""The catalogue as a human-readable price book (text and CSV).

For each plan: name, currency, base fee and legacy flag, then each metered
charge with its allowance and prices.  Tiers are written the way a customer
would read them:

    graduated   first 1,000,000 calls at 0.0004 USD
                next 9,000,000 calls at 0.0003 USD
                above 10,000,000 calls at 0.0002 USD
    volume      1-1,000,000 calls: all at 0.0004 USD
    package     0.05 USD per block of 100 seats (partial blocks charged in full)
    per_unit    0.0005 USD per call
    flat        0.10 USD once, whatever the quantity

A tier's ``flat_fee`` is appended as "+ 5.00 USD flat" when non-zero.  Prices
are printed with all their significant digits (never rounded; the catalogue
is the source of truth).  Units are the metric's unit, singularised by
dropping a trailing "s" for the "per <unit>" forms ("calls" -> "call").

Nothing here rates anything: for "what would X cost" use quotes.py.
"""

from .csvutil import write_rows
from .money import dec
from .pricing import fmt_qty
from .render.fmt import format_amount, format_unit_price


def _singular(unit):
    return unit[:-1] if unit.endswith("s") and len(unit) > 1 else unit


def _price(value, currency):
    return f"{format_unit_price(value)} {currency}"


def _base_fee(plan):
    from .money import Money
    return f"{format_amount(Money(plan.base_fee, plan.currency))} {plan.currency}"


def allowance_text(charge, metric):
    """'100,000 calls included' or '' when the charge has no allowance."""
    inc = charge.price.included
    if not inc:
        return ""
    return f"{fmt_qty(inc)} {metric.unit} included"


def _flat(tier, currency):
    return f" + {_price(tier.flat_fee, currency)} flat" if tier.flat_fee else ""


def tier_lines(charge, metric, currency):
    """The price statements of one charge as a list of strings."""
    p = charge.price
    unit = metric.unit
    if p.model == "per_unit":
        return [f"{_price(p.unit_price, currency)} per {_singular(unit)}"]
    if p.model == "flat":
        return [f"{_price(p.unit_price, currency)} once, whatever the quantity"]
    if p.model == "package":
        size = fmt_qty(p.package_size)
        return [f"{_price(p.unit_price, currency)} per block of {size} {unit} "
                f"(partial blocks charged in full)"]
    lines = []
    lower = dec(0)
    for i, tier in enumerate(p.tiers):
        if p.model == "graduated":
            if tier.up_to is None:
                head = f"above {fmt_qty(lower)} {unit}"
            else:
                span = tier.up_to - lower
                head = f"{'first' if i == 0 else 'next'} {fmt_qty(span)} {unit}"
            lines.append(f"{head} at {_price(tier.unit_price, currency)}{_flat(tier, currency)}")
        else:  # volume
            if tier.up_to is None:
                head = f"above {fmt_qty(lower)} {unit}"
            else:
                start = lower + 1 if lower == lower.to_integral_value() else lower
                head = f"{fmt_qty(start)}-{fmt_qty(tier.up_to)} {unit}"
            lines.append(f"{head}: all at {_price(tier.unit_price, currency)}{_flat(tier, currency)}")
        if tier.up_to is not None:
            lower = tier.up_to
    return lines


def render_price_book(catalog, *, include_legacy=True):
    """The whole price book as text (72 columns)."""
    out = ["KETTLE CLOUD PRICE BOOK", "=" * 72]
    plans = [p for p in catalog.plans() if include_legacy or not p.legacy]
    if not plans:
        return "\n".join(out + ["(no plans)"]) + "\n"
    for plan in plans:
        title = f"{plan.name} [{plan.id}]" + ("  (legacy: existing subscribers only)" if plan.legacy else "")
        out.append(title)
        out.append(f"  Base fee: {_base_fee(plan)} per billing period")
        if not plan.charges:
            out.append("  No metered charges.")
        for charge in plan.charges:
            metric = catalog.metrics.get(charge.metric)
            out.append(f"  {metric.name} (billed by {_aggregation_words(metric.aggregation)})")
            allowance = allowance_text(charge, metric)
            if allowance:
                out.append(f"    {allowance}")
            for line in tier_lines(charge, metric, plan.currency):
                out.append(f"    {line}")
        out.append("-" * 72)
    return "\n".join(out) + "\n"


def _aggregation_words(agg):
    return {"sum": "total in the period", "max": "peak in the period",
            "last": "last reading in the period"}[agg]


CSV_HEADER = ("plan", "name", "currency", "legacy", "base_fee", "metric", "model", "included",
              "tier", "up_to", "unit_price", "flat_fee")


def price_book_rows(catalog, *, include_legacy=True):
    """One row per (plan, charge, tier); a plan without charges gets one row with blank charge fields.

    Non-tiered charges have a single row with tier ``1`` and a blank ``up_to``.
    """
    rows = []
    for plan in catalog.plans():
        if plan.legacy and not include_legacy:
            continue
        head = (plan.id, plan.name, plan.currency, "yes" if plan.legacy else "no", format(plan.base_fee, "f"))
        if not plan.charges:
            rows.append(head + ("", "", "", "", "", "", ""))
            continue
        for charge in plan.charges:
            p = charge.price
            inc = fmt_qty(p.included).replace(",", "")
            if p.model in ("graduated", "volume"):
                for i, tier in enumerate(p.tiers, 1):
                    rows.append(head + (charge.metric, p.model, inc, i,
                                        "" if tier.up_to is None else format(tier.up_to.normalize(), "f"),
                                        format(tier.unit_price.normalize(), "f"),
                                        format(tier.flat_fee.normalize(), "f")))
            else:
                price = p.unit_price
                rows.append(head + (charge.metric, p.model, inc, 1, "", format(price.normalize(), "f"), "0"))
    return rows


def price_book_csv(catalog, *, include_legacy=True):
    return write_rows(CSV_HEADER, price_book_rows(catalog, include_legacy=include_legacy))
