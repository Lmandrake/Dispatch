"""Price quotes for sales (docs/PRICING.md, "Quotes").

A quote answers "what would this customer pay per month on each plan for
this usage?".  It rates the expected quantities with the same code as
invoicing (so a quote can never disagree with an invoice), adds the base
fee, converts to the requested currency at the rate of ``on`` and rounds
each line half-up.  Tax is not included: quotes are pre-tax.
"""

from dataclasses import dataclass, field

from .money import Money, dec


@dataclass
class QuoteLine:
    metric: str
    quantity: object
    amount: Money


@dataclass
class Quote:
    plan: str
    currency: str
    base: Money
    lines: list = field(default_factory=list)

    @property
    def total(self):
        t = self.base
        for ln in self.lines:
            t = t + ln.amount
        return t


def quote(catalog, plan_id, usage, currency, converter, on):
    """``usage``: {metric: quantity}.  Metrics the plan does not charge are free."""
    plan = catalog.plan(plan_id)
    base = converter.convert(Money(plan.base_fee, plan.currency), currency, on).rounded()
    q = Quote(plan.id, currency, base)
    for charge in plan.charges:
        qty = dec(str(usage.get(charge.metric, 0)))
        rating = plan.rate(charge.metric, qty)
        amt = converter.convert(Money(rating.amount, plan.currency), currency, on).rounded()
        q.lines.append(QuoteLine(charge.metric, qty, amt))
    return q


def compare(catalog, usage, currency, converter, on, *, include_legacy=False):
    """Quotes for every plan, cheapest first (ties by plan id)."""
    out = []
    for plan in catalog.plans():
        if plan.legacy and not include_legacy:
            continue
        out.append(quote(catalog, plan.id, usage, currency, converter, on))
    out.sort(key=lambda q: (q.total.amount, q.plan))
    return out


def render_compare(quotes):
    from .render.fmt import format_amount
    if not quotes:
        return "no plans\n"
    cur = quotes[0].currency
    lines = [f"{'plan':<14}{'base':>12}{'usage':>12}{'total':>14}  ({cur}, pre-tax)"]
    for q in quotes:
        usage = q.total - q.base
        lines.append(f"{q.plan:<14}{format_amount(q.base):>12}{format_amount(usage):>12}{format_amount(q.total):>14}")
    return "\n".join(lines) + "\n"
