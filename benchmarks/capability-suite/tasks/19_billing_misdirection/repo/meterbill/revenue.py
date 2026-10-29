"""Revenue recognition schedule (docs/LEDGER.md, "Revenue recognition").

Finance reports revenue by *calendar month in the customer's timezone*,
which is not the billing period when the anchor day is not 1.

* A base line is recognised ratably: an equal share per local day of its
  segment, the minor units that do not divide evenly going to the earliest
  days (money.allocate with equal weights).
* A usage line is recognised in proportion to the billed quantity per local
  day; for ``max`` and ``last`` metrics, which have no meaningful per-day
  split, the whole line is recognised on the segment's last day.
* Discounts reduce revenue in proportion to the lines they apply to; for
  simplicity the schedule spreads each coupon over the days of the period
  equally.  Tax and late fees are not revenue.

``schedule(inv, records, catalog)`` returns {"YYYY-MM": Money}.
"""

from datetime import timedelta

from .money import Money, allocate
from .timeutil import local_date


def _days(start, end):
    d = start
    while d < end:
        yield d
        d += timedelta(days=1)


def _month(day):
    return f"{day.year:04d}-{day.month:02d}"


def _add(acc, key, amount):
    acc[key] = acc.get(key, Money.zero(amount.currency)) + amount


def schedule(inv, records, catalog):
    cur = inv.currency
    out = {}
    tz = inv.period.tz
    for ln in inv.lines:
        if ln.kind == "fee" or not ln.amount:
            continue
        days = list(_days(ln.start, ln.end))
        if ln.kind == "base":
            parts = allocate(ln.amount, [1] * len(days))
            for d, part in zip(days, parts):
                _add(out, _month(d), part)
            continue
        metric = catalog.metrics.get(ln.metric)
        if metric.aggregation != "sum":
            _add(out, _month(days[-1]), ln.amount)
            continue
        per_day = {d: 0 for d in days}
        for r in records:
            if r.customer != inv.customer.id or r.metric != ln.metric:
                continue
            d = local_date(r.at, tz)
            if d in per_day:
                per_day[d] += r.quantity
        weights = [per_day[d] for d in days]
        if not any(weights):
            weights = [1] * len(days)
        for d, part in zip(days, allocate(ln.amount, weights)):
            _add(out, _month(d), part)
    period_days = list(_days(inv.period.start, inv.period.end))
    for disc in inv.discounts:
        for d, part in zip(period_days, allocate(disc.amount, [1] * len(period_days))):
            _add(out, _month(d), -part)
    return dict(sorted(out.items()))


def schedule_total(sched, currency):
    total = Money.zero(currency)
    for v in sched.values():
        total = total + v
    return total


def render_schedule(inv, sched):
    from .render.fmt import format_amount
    lines = [f"Revenue schedule {inv.number} ({inv.currency})"]
    for month, amount in sched.items():
        lines.append(f"  {month}  {format_amount(amount):>14}")
    lines.append(f"  {'total':<7}  {format_amount(schedule_total(sched, inv.currency)):>14}")
    return "\n".join(lines) + "\n"
