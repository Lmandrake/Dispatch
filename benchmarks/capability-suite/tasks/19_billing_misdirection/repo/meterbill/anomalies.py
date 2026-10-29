"""Usage anomaly detection for the support dashboard.

Flags, per customer and ``sum`` metric, the local days whose usage is far
above that customer's typical day: more than ``factor`` times the median of
the other days of the period (and at least ``min_qty``).  Also flags gaps:
runs of ``gap_days`` or more consecutive days with no records at all for a
customer that normally reports daily, which usually means a broken feed.

The detector only reads records; it never changes what is billed.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from statistics import median


@dataclass(frozen=True)
class Spike:
    customer: str
    metric: str
    day: object
    quantity: Decimal
    typical: Decimal

    @property
    def ratio(self):
        return (self.quantity / self.typical).quantize(Decimal("0.1")) if self.typical else None


@dataclass(frozen=True)
class Gap:
    customer: str
    first: object
    last: object

    @property
    def days(self):
        return (self.last - self.first).days + 1


def daily_totals(records, customer, metric, period):
    out = {}
    d = period.start
    while d < period.end:
        out[d] = Decimal(0)
        d += timedelta(days=1)
    for r in records:
        if r.customer == customer and r.metric == metric and period.contains(r.at):
            out[period.local_day(r.at)] += r.quantity
    return out


def spikes(records, customer, metric, period, *, factor=Decimal(4), min_qty=Decimal(1000)):
    totals = daily_totals(records, customer, metric, period)
    found = []
    for day, q in totals.items():
        others = [v for d, v in totals.items() if d != day]
        if not others:
            continue
        typical = Decimal(median(others))
        if q >= min_qty and typical > 0 and q > typical * factor:
            found.append(Spike(customer, metric, day, q, typical))
    return found


def gaps(records, customer, period, *, gap_days=3):
    seen = {period.local_day(r.at) for r in records if r.customer == customer and period.contains(r.at)}
    if len(seen) < (period.days // 2):
        return []          # not a daily reporter
    out = []
    run_start = None
    d = period.start
    while d < period.end:
        if d not in seen:
            run_start = run_start or d
        else:
            if run_start and (d - run_start).days >= gap_days:
                out.append(Gap(customer, run_start, d - timedelta(days=1)))
            run_start = None
        d += timedelta(days=1)
    if run_start and (period.end - run_start).days >= gap_days:
        out.append(Gap(customer, run_start, period.end - timedelta(days=1)))
    return out
