"""Per-customer daily usage report (the "usage" CLI command).

For one customer and cycle: one row per local day of the billing period with
the day's total per ``sum`` metric and the day's last reading for the
others, then a totals row holding each metric's billed quantity (with the
metric's own aggregation, over the whole period).
"""

from datetime import timedelta
from decimal import Decimal

from .periods import billing_period


def daily_usage(customer, cycle, records, metrics):
    period = billing_period(cycle, customer.anchor_day, customer.timezone)
    mine = [r for r in records if r.customer == customer.id and period.contains(r.at)]
    days = []
    d = period.start
    while d < period.end:
        days.append(d)
        d += timedelta(days=1)
    table = {day: {} for day in days}
    for m in metrics:
        recs = [r for r in mine if r.metric == m.id]
        by_day = {}
        for r in recs:
            by_day.setdefault(period.local_day(r.at), []).append(r)
        for day in days:
            table[day][m.id] = m.aggregate(by_day.get(day, [])) if m.aggregation == "sum" or day in by_day else None
    totals = {m.id: m.aggregate([r for r in mine if r.metric == m.id]) for m in metrics}
    return period, table, totals


def render_usage(customer, cycle, records, metrics):
    from .render.fmt import format_qty
    period, table, totals = daily_usage(customer, cycle, records, metrics)
    ms = list(metrics)
    head = f"{'day':<12}" + "".join(f"{m.id:>16}" for m in ms)
    out = [f"Usage {customer.id} {period.label()} ({period.tz})", head]
    for day, row in table.items():
        cells = []
        for m in ms:
            v = row[m.id]
            cells.append(f"{'-' if v is None else format_qty(v, m.precision):>16}")
        out.append(f"{day.isoformat():<12}" + "".join(cells))
    out.append(f"{'billed':<12}" + "".join(f"{format_qty(totals[m.id] or Decimal(0), m.precision):>16}" for m in ms))
    return "\n".join(out) + "\n"
