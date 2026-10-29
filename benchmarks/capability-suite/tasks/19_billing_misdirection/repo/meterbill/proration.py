"""Proration of base fees on mid-cycle plan changes (docs/SUBSCRIPTIONS.md).

Each plan segment of a billing period pays a fraction of its plan's base
fee.  The fraction is exact (``fractions.Fraction``); the amount is carried
at PRECISE precision and only rounded on the invoice line.
"""

import calendar
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .money import precise


@dataclass(frozen=True)
class Proration:
    plan: str
    start: object
    end: object
    days: int
    period_days: int
    fraction: Fraction
    amount: Decimal      # PRECISE, plan currency

    @property
    def full(self):
        return self.fraction == 1


def fraction_of(days, period_days):
    if period_days <= 0:
        raise ValueError("period has no days")
    if not 0 <= days <= period_days:
        raise ValueError(f"segment of {days} days does not fit a {period_days}-day period")
    return Fraction(days, period_days)


def prorate(base_fee, segment, period):
    """Prorated base fee for one Segment of a BillingPeriod."""
    period_days = calendar.monthrange(segment.start.year, segment.start.month)[1]
    frac = fraction_of(segment.days, period_days)
    amount = precise(Decimal(base_fee) * frac.numerator / frac.denominator).quantize(Decimal("0.01"))
    return Proration(segment.plan, segment.start, segment.end, segment.days, period_days, frac, amount)


def prorate_all(catalog, segments, period):
    """Prorations for every segment, in order."""
    return [prorate(catalog.plan(s.plan).base_fee, s, period) for s in segments]
