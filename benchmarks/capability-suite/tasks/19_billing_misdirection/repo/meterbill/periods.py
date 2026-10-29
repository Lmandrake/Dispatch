"""Billing periods.

A customer is billed monthly on an *anchor day* (1-28 in the customer file;
29-31 are accepted and clamp to the last day of short months).  The billing
period of cycle ``YYYY-MM`` is the one that *starts* in that month:

    anchor 1,  cycle 2026-03  ->  2026-03-01 .. 2026-04-01 (exclusive)
    anchor 15, cycle 2026-03  ->  2026-03-15 .. 2026-04-15 (exclusive)

Periods are made of local calendar days in the customer's timezone
(docs/PERIODS.md).  Usage records are assigned to a period by comparing
their UTC instant with the period's UTC boundaries.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .errors import PeriodError
from .timeutil import local_date, local_midnight, zone

_CYCLE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_cycle(text):
    """``'2026-03'`` -> (2026, 3); PeriodError on anything else."""
    m = _CYCLE.match(str(text).strip())
    if not m:
        raise PeriodError(f"bad billing cycle {text!r}; expected YYYY-MM")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise PeriodError(f"bad month in cycle {text!r}")
    return year, month


def format_cycle(year, month):
    return f"{year:04d}-{month:02d}"


def next_cycle(cycle):
    year, month = parse_cycle(cycle)
    month += 1
    if month == 13:
        year, month = year + 1, 1
    return format_cycle(year, month)


def prev_cycle(cycle):
    year, month = parse_cycle(cycle)
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return format_cycle(year, month)


def cycles_between(first, last):
    """Number of cycles from ``first`` to ``last`` (0 when equal)."""
    y1, m1 = parse_cycle(first)
    y2, m2 = parse_cycle(last)
    return (y2 - y1) * 12 + (m2 - m1)


def anchored_day(year, month, anchor):
    """The anchor day in a given month, clamped to the month's length."""
    if not 1 <= anchor <= 31:
        raise PeriodError(f"anchor day {anchor} out of range 1-31")
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor, last))


@dataclass(frozen=True)
class BillingPeriod:
    cycle: str
    tz: str
    start: date          # first local day of service
    end: date            # local day after the last day of service
    start_utc: datetime
    end_utc: datetime

    @property
    def days(self):
        """Number of local calendar days in the period."""
        return (self.end - self.start).days

    @property
    def last_day(self):
        return date.fromordinal(self.end.toordinal() - 1)

    def contains(self, instant):
        """True when the UTC instant falls inside the period."""
        return self.start_utc <= instant < self.end_utc

    def contains_day(self, day):
        return self.start <= day < self.end

    def local_day(self, instant):
        return local_date(instant, self.tz)

    def label(self):
        return f"{self.start.isoformat()} to {self.last_day.isoformat()}"

    def hours(self):
        """Length in hours, which is not 24 * days across a DST change."""
        return (self.end_utc - self.start_utc).total_seconds() / 3600


def billing_period(cycle, anchor, tz):
    """The BillingPeriod of ``cycle`` for a customer anchored on ``anchor`` in ``tz``."""
    year, month = parse_cycle(cycle)
    zone(tz)  # validate early
    start = anchored_day(year, month, anchor)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    end = anchored_day(ny, nm, anchor)
    start_utc = local_midnight(start, tz)
    end_utc = start_utc + timedelta(days=(end - start).days)
    return BillingPeriod(cycle, tz, start, end, start_utc, end_utc)


def period_for_day(day, anchor, tz):
    """The BillingPeriod that contains local calendar ``day``."""
    candidate = anchored_day(day.year, day.month, anchor)
    if day >= candidate:
        cycle = format_cycle(day.year, day.month)
    else:
        cycle = prev_cycle(format_cycle(day.year, day.month))
    return billing_period(cycle, anchor, tz)
