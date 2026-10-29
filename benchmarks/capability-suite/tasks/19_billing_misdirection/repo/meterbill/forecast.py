"""End-of-period forecast for the customer portal ("your bill so far").

Given the records up to ``as_of`` (an instant inside the period), the
forecast projects each metric to the end of the period and prices the
projection with the normal invoice code:

* ``sum`` metrics are extrapolated linearly by elapsed time
  (quantity * period length / elapsed), rounded up to a whole unit;
* ``max`` and ``last`` metrics are assumed to stay at their current value.

The forecast is pre-tax and ignores coupons and credits; the portal says so.
"""

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from .money import Money


@dataclass
class ForecastLine:
    metric: str
    so_far: Decimal
    projected: Decimal
    amount: Money


@dataclass
class Forecast:
    customer: str
    as_of: object
    currency: str
    base: Money
    lines: list = field(default_factory=list)

    @property
    def total(self):
        t = self.base
        for ln in self.lines:
            t = t + ln.amount
        return t


def forecast(ctx, customer, period, records, as_of):
    if not period.contains(as_of):
        raise ValueError("as_of must fall inside the period")
    cur = customer.currency
    elapsed = (as_of - period.start_utc).total_seconds()
    length = (period.end_utc - period.start_utc).total_seconds()
    plan_id = ctx.subscriptions.plan_on(customer.id, period.local_day(as_of))
    if plan_id is None:
        return Forecast(customer.id, as_of, cur, Money.zero(cur))
    plan = ctx.catalog.plan(plan_id)
    rate_day = period.last_day
    base = ctx.converter.convert(Money(plan.base_fee, plan.currency), cur, rate_day).rounded()
    fc = Forecast(customer.id, as_of, cur, base)
    mine = [r for r in records if r.customer == customer.id and period.start_utc <= r.at <= as_of]
    for charge in plan.charges:
        metric = ctx.catalog.metrics.get(charge.metric)
        recs = [r for r in mine if r.metric == metric.id]
        so_far = metric.aggregate(recs)
        if metric.aggregation == "sum" and elapsed > 0:
            projected = (so_far * Decimal(length) / Decimal(elapsed)).to_integral_value(rounding=ROUND_CEILING)
        else:
            projected = so_far
        rating = plan.rate(metric.id, projected)
        amount = ctx.converter.convert(Money(rating.amount, plan.currency), cur, rate_day).rounded()
        fc.lines.append(ForecastLine(metric.id, so_far, projected, amount))
    return fc
