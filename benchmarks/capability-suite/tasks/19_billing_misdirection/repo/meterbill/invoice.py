"""Assembling one customer's invoice for one billing cycle (docs/INVOICES.md).

Order of operations (finance sign-off, 2025-09):

1. Billing period in the customer's timezone (periods.py).
2. Plan segments from the subscription history (subscriptions.py).
3. Usage assigned to segments (usage.py) and aggregated per metric.
4. Lines, in segment order: the prorated base fee of the segment's plan, then
   one line per metered charge of that plan, in catalogue order.  Every
   amount is computed in the plan currency at PRECISE precision, converted to
   the invoice currency at the rate of the period's last day, and only then
   rounded half-up to the minor unit.  A line's rounded amount is final.
5. Subtotal = sum of the rounded line amounts (plus late fees, if any).
6. Coupons (discounts.py), computed from the rounded lines.
7. Tax (tax.py), by the jurisdiction's rounding rule.
8. The total.
9. Prepaid credit (credits.py); what remains is the amount due.

Nothing in this module rounds a second time, and the renderers never round:
every figure they print is a field of the Invoice.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from .credits import apply_credits, usable_grants
from .discounts import active_coupons, apply_coupons, total_discount
from .money import ZERO, Money, round_to
from .numbering import due_date, invoice_number, issue_date
from .periods import billing_period
from .proration import prorate
from .usage import assign


@dataclass(frozen=True)
class LineDetail:
    label: str
    quantity: Decimal
    unit_price: Decimal
    amount: Money         # invoice currency, PRECISE (informational)
    precision: int = 0    # display precision of ``quantity``


@dataclass(frozen=True)
class InvoiceLine:
    kind: str             # "base" | "usage" | "fee"
    description: str
    quantity: Decimal
    unit: str
    amount: Money         # invoice currency, rounded
    plan: str = ""
    metric: str = ""
    start: object = None
    end: object = None
    fraction: Fraction = Fraction(1)
    details: tuple = ()
    precision: int = 0
    taxable: bool = True


@dataclass
class Invoice:
    number: str
    customer: object
    cycle: str
    period: object
    issued: object
    due: object
    currency: str
    rate_day: object
    lines: list = field(default_factory=list)
    subtotal: Money = None
    discounts: list = field(default_factory=list)
    discount_total: Money = None
    tax: object = None            # TaxResult
    late_fees: Money = None
    total: Money = None
    credits: list = field(default_factory=list)
    credit_total: Money = None
    amount_due: Money = None
    notes: list = field(default_factory=list)
    usage_counts: dict = field(default_factory=dict)

    @property
    def taxable(self):
        return self.tax.taxable

    def line_total(self, kind):
        total = Money.zero(self.currency)
        for ln in self.lines:
            if ln.kind == kind:
                total = total + ln.amount
        return total

    def summary(self):
        return {
            "number": self.number,
            "customer": self.customer.id,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "discount": self.discount_total,
            "tax": self.tax.tax,
            "total": self.total,
            "credit": self.credit_total,
            "due": self.amount_due,
        }


@dataclass
class BillingContext:
    """Everything an invoice needs that is not the customer itself."""

    catalog: object
    subscriptions: object
    tax: object
    converter: object
    coupons: dict = field(default_factory=dict)
    redemptions: list = field(default_factory=list)
    grants: list = field(default_factory=list)
    late_fees: dict = field(default_factory=dict)   # customer id -> [(description, Money)]


def short_day(day):
    return day.strftime("%b %d").replace(" 0", " ")


def segment_label(start, end_exclusive):
    from datetime import timedelta
    last = end_exclusive - timedelta(days=1)
    if start == last:
        return short_day(start)
    return f"{short_day(start)}-{short_day(last)}"


def _to_invoice(ctx, amount, plan_currency, cur, rate_day):
    m = ctx.converter.convert(Money(amount, plan_currency), cur, rate_day)
    return m


def build_lines(ctx, customer, period, pu, rate_day):
    cur = customer.currency
    lines = []
    for su in pu.segments:
        seg = su.segment
        plan = ctx.catalog.plan(seg.plan)
        pr = prorate(plan.base_fee, seg, period)
        base_exact = _to_invoice(ctx, pr.amount, plan.currency, cur, rate_day)
        span = segment_label(seg.start, seg.end)
        desc = f"{plan.name} plan, {span}"
        if not pr.full:
            desc += f" ({pr.days}/{pr.period_days} days)"
        lines.append(InvoiceLine(
            kind="base", description=desc, quantity=Decimal(1), unit="period",
            amount=base_exact.rounded(), plan=plan.id, start=seg.start, end=seg.end,
            fraction=pr.fraction))
        for charge in plan.charges:
            metric = ctx.catalog.metrics.get(charge.metric)
            recs = su.records.get(charge.metric, [])
            qty = metric.aggregate(recs)
            rating = plan.rate(charge.metric, qty)
            exact = _to_invoice(ctx, rating.amount, plan.currency, cur, rate_day)
            details = tuple(
                LineDetail(s.label, s.quantity, s.unit_price,
                           _to_invoice(ctx, s.amount, plan.currency, cur, rate_day),
                           0 if charge.price.model == "package" else metric.precision)
                for s in rating.slices if s.label)
            desc = charge.description or metric.name
            if len(pu.segments) > 1:
                desc += f", {span}"
            lines.append(InvoiceLine(
                kind="usage", description=desc, quantity=qty, unit=metric.unit,
                amount=exact.rounded(), plan=plan.id, metric=metric.id,
                start=seg.start, end=seg.end, details=details, precision=metric.precision))
    return lines


def build_invoice(ctx, customer, cycle, records, *, revision=0):
    """The Invoice of ``customer`` for ``cycle`` from that customer's records."""
    cur = customer.currency
    period = billing_period(cycle, customer.anchor_day, customer.timezone)
    rate_day = period.last_day
    segments = ctx.subscriptions.segments(customer.id, period)
    pu = assign([r for r in records if r.customer == customer.id], period, segments)
    inv = Invoice(
        number=invoice_number(cycle, customer.id, revision),
        customer=customer, cycle=cycle, period=period,
        issued=issue_date(period), due=due_date(period, customer.terms_days),
        currency=cur, rate_day=rate_day)
    inv.usage_counts = {
        "billed": pu.billed_count(), "unbilled": len(pu.unbilled), "outside": pu.outside}
    inv.lines = build_lines(ctx, customer, period, pu, rate_day)

    fees = []
    for desc, amount in ctx.late_fees.get(customer.id, []):
        fee = ctx.converter.convert(amount, cur, rate_day).rounded()
        fees.append(fee)
        inv.lines.append(InvoiceLine(kind="fee", description=desc, quantity=Decimal(1),
                                     unit="fee", amount=fee, taxable=False))
    inv.late_fees = Money.zero(cur)
    for f in fees:
        inv.late_fees = inv.late_fees + f

    taxable_lines = [ln for ln in inv.lines if ln.taxable]
    charges = Money.zero(cur)
    for ln in taxable_lines:
        charges = charges + ln.amount
    inv.subtotal = charges + inv.late_fees

    coupons = active_coupons(ctx.coupons, ctx.redemptions, customer.id, cycle)
    inv.discounts = apply_coupons(coupons, [(ln.kind, ln.amount) for ln in taxable_lines],
                                  charges, ctx.converter, rate_day)
    inv.discount_total = total_discount(inv.discounts, cur)

    inv.tax = ctx.tax.compute(customer, [ln.amount for ln in taxable_lines], Money.zero(cur))
    inv.total = inv.tax.taxable + inv.tax.tax - inv.discount_total + inv.late_fees

    grants = usable_grants(ctx.grants, customer.id, inv.issued)
    inv.credits, inv.amount_due = apply_credits(grants, inv.total, ctx.converter, rate_day)
    inv.credit_total = Money.zero(cur)
    for use in inv.credits:
        inv.credit_total = inv.credit_total + use.applied

    if inv.tax.reverse_charged:
        inv.notes.append(inv.tax.note)
    if pu.unbilled:
        inv.notes.append(f"{len(pu.unbilled)} usage record(s) fall outside the subscription and were not billed.")
    if customer.status == "suspended":
        inv.notes.append("Account suspended for non-payment: service resumes once this invoice is paid.")
    return inv


def invoice_check(inv):
    """Internal consistency checks; returns a list of problems (empty = fine)."""
    problems = []
    cur = inv.currency
    s = Money.zero(cur)
    for ln in inv.lines:
        if ln.amount != ln.amount.rounded():
            problems.append(f"line {ln.description!r} is not rounded")
        s = s + ln.amount
    if s != inv.subtotal:
        problems.append("lines do not add up to the subtotal")
    if inv.discount_total > inv.subtotal:
        problems.append("discount exceeds subtotal")
    if inv.total != inv.subtotal - inv.discount_total + inv.tax.tax:
        problems.append("total != subtotal - discount + tax")
    if inv.amount_due != inv.total - inv.credit_total:
        problems.append("amount due != total - credit")
    if inv.amount_due.is_negative():
        problems.append("amount due is negative")
    return problems
