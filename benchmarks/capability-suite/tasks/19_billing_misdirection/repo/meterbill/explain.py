"""Explain an invoice line: every step from feed records to the printed amount.

Support uses this when a customer disputes a figure.  ``explain_line``
re-derives one line of a built invoice with the same functions the invoice
used and returns the steps as text, so the explanation can never drift from
the computation:

    records     how many usage records were assigned to the segment, the
                first and last instant, and the aggregation applied
    quantity    the billed quantity, the allowance taken off
    rating      each tier slice (quantity @ unit price = amount)
    conversion  plan currency -> invoice currency: the rate day and cross rate
    rounding    the amount before and after rounding to the minor unit
"""

from dataclasses import dataclass, field

from .money import Money
from .timeutil import format_instant
from .usage import assign


@dataclass
class Explanation:
    invoice: str
    line: str
    steps: list = field(default_factory=list)

    def add(self, label, text):
        self.steps.append((label, text))

    def render(self):
        out = [f"{self.invoice}: {self.line}"]
        width = max((len(lbl) for lbl, _ in self.steps), default=0)
        for label, text in self.steps:
            out.append(f"  {label:<{width}}  {text}")
        return "\n".join(out) + "\n"


def _find_line(inv, index):
    if not 0 <= index < len(inv.lines):
        raise IndexError(f"{inv.number} has {len(inv.lines)} lines; no line {index + 1}")
    return inv.lines[index]


def explain_line(ctx, inv, records, index):
    """Explanation of line ``index`` (0-based) of ``inv``."""
    ln = _find_line(inv, index)
    ex = Explanation(inv.number, ln.description)
    period = inv.period
    ex.add("period", f"{period.label()} ({period.tz}), "
                     f"{format_instant(period.start_utc)} .. {format_instant(period.end_utc)}")
    rate_day = inv.rate_day
    if ln.kind == "fee":
        ex.add("fee", f"late fee from dunning, {ln.amount} (not taxed, not discounted)")
        return ex
    plan = ctx.catalog.plan(ln.plan)
    if plan.currency != inv.currency:
        rate = ctx.converter.cross_rate(plan.currency, inv.currency, rate_day)
        ex.add("conversion", f"{plan.currency} -> {inv.currency} at {rate} (rate day {rate_day.isoformat()})")
    if ln.kind == "base":
        ex.add("base fee", f"{plan.base_fee} {plan.currency} x {ln.fraction.numerator}/{ln.fraction.denominator}")
        ex.add("amount", f"{ln.amount}")
        return ex
    segments = ctx.subscriptions.segments(inv.customer.id, period)
    pu = assign([r for r in records if r.customer == inv.customer.id], period, segments)
    su = next((s for s in pu.segments if s.segment.start == ln.start and s.segment.plan == ln.plan), None)
    recs = su.records.get(ln.metric, []) if su else []
    metric = ctx.catalog.metrics.get(ln.metric)
    if recs:
        first = min(r.at for r in recs)
        last = max(r.at for r in recs)
        ex.add("records", f"{len(recs)} record(s), {format_instant(first)} .. {format_instant(last)}")
    else:
        ex.add("records", "none")
    ex.add("aggregation", f"{metric.aggregation} -> {ln.quantity}")
    rating = plan.rate(ln.metric, ln.quantity)
    charge = plan.charge_for(ln.metric)
    if charge.price.included:
        ex.add("included", f"{charge.price.included} free -> {rating.chargeable} chargeable")
    for s in rating.slices:
        ex.add("rating", f"{s.label or ln.metric}: {s.quantity} @ {s.unit_price} = {s.amount} {plan.currency}")
    exact = ctx.converter.convert(Money(rating.amount, plan.currency), inv.currency, rate_day)
    ex.add("rounding", f"{exact.amount} -> {ln.amount.amount} {inv.currency}")
    return ex


def explain_invoice(ctx, inv, records):
    return "".join(explain_line(ctx, inv, records, i).render() for i in range(len(inv.lines)))
