"""Subscription history (data/subscriptions.csv), per docs/SUBSCRIPTIONS.md.

    customer,plan,effective
    C01,team,2025-11-01
    C01,business,2026-03-12

A row says: from local calendar day ``effective`` the customer is on
``plan``.  The special plan id ``none`` ends the subscription (no base fee,
no usage charges from that day).  Ordering rules: docs/SUBSCRIPTIONS.md.
"""

from dataclasses import dataclass

from .csvutil import read_rows
from .errors import ConfigError, UnknownCustomer, UnknownPlan
from .timeutil import parse_date

NO_PLAN = "none"


@dataclass(frozen=True)
class Change:
    customer: str
    plan: str
    effective: object  # date


@dataclass(frozen=True)
class Segment:
    """A run of consecutive days inside one period on one plan."""

    plan: str
    start: object   # first day (date)
    end: object     # day after the last day (date)

    @property
    def days(self):
        return (self.end - self.start).days


class Subscriptions:
    def __init__(self, changes):
        self._by_customer = {}
        for ch in changes:
            self._by_customer.setdefault(ch.customer, []).append(ch)
        for cid, lst in self._by_customer.items():
            lst.sort(key=lambda c: (c.effective, c.plan))
            collapsed = []
            for ch in lst:
                if collapsed and collapsed[-1].effective == ch.effective:
                    collapsed[-1] = ch
                else:
                    collapsed.append(ch)
            self._by_customer[cid] = collapsed

    def history(self, cid):
        return list(self._by_customer.get(cid, []))

    def plan_on(self, cid, day):
        """Plan id in effect on local ``day``, or None before the first row."""
        current = None
        for ch in self._by_customer.get(cid, []):
            if ch.effective <= day:
                current = ch.plan
            else:
                break
        return None if current in (None, NO_PLAN) else current

    def segments(self, cid, period):
        """Segments covering ``period`` (days without a plan are left out)."""
        cuts = [period.start]
        for ch in self._by_customer.get(cid, []):
            if period.start < ch.effective < period.end:
                cuts.append(ch.effective)
        cuts.append(period.end)
        out = []
        for a, b in zip(cuts, cuts[1:]):
            plan = self.plan_on(cid, a)
            if plan is None or a == b:
                continue
            if out and out[-1].plan == plan and out[-1].end == a:
                out[-1] = Segment(plan, out[-1].start, b)
            else:
                out.append(Segment(plan, a, b))
        return out

    def customers(self):
        return sorted(self._by_customer)


def parse_subscriptions(text, *, customers=None, catalog=None, source="subscriptions.csv"):
    changes = []
    for lineno, r in read_rows(text, required=("customer", "plan", "effective"), source=source):
        cid = r["customer"].upper()
        if customers is not None and cid not in customers:
            raise UnknownCustomer(f"{source} line {lineno}: unknown customer {cid}")
        plan = r["plan"]
        if plan != NO_PLAN and catalog is not None and plan not in catalog:
            raise UnknownPlan(f"{source} line {lineno}: unknown plan {plan!r}")
        try:
            day = parse_date(r["effective"])
        except ValueError as e:
            raise ConfigError(f"line {lineno}: {e}", source=source) from None
        changes.append(Change(cid, plan, day))
    subs = Subscriptions(changes)
    if catalog is not None:
        for cid in subs.customers():
            hist = subs.history(cid)
            for prev, ch in zip(hist, hist[1:]):
                if ch.plan != NO_PLAN and catalog.plan(ch.plan).legacy and ch.plan != prev.plan:
                    raise ConfigError(f"{cid}: cannot switch to legacy plan {ch.plan} on {ch.effective}", source=source)
    return subs
