"""Committed-spend contracts (data/commitments.csv), a true-up report.

Enterprise customers can commit to a minimum spend over a contract term:

    customer,contract,currency,minimum,start_cycle,end_cycle
    C11,ENT-0042,EUR,24000.00,2026-01,2026-12

At the end of the term, if the customer's pre-tax charges (subtotal minus
coupons) over the term's invoices fall short of the minimum, the shortfall
is billed as a true-up.  Mid-term, ``progress`` shows how far along the
customer is, and ``projected_shortfall`` extrapolates linearly from the
cycles so far.

Only the report lives here; the true-up invoice itself is raised by hand.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .csvutil import read_rows
from .errors import ConfigError
from .money import Money, dec, round_to
from .periods import cycles_between, parse_cycle


@dataclass(frozen=True)
class Commitment:
    customer: str
    contract: str
    minimum: Money
    start_cycle: str
    end_cycle: str

    @property
    def cycles(self):
        return cycles_between(self.start_cycle, self.end_cycle) + 1

    def covers(self, cycle):
        return 0 <= cycles_between(self.start_cycle, cycle) < self.cycles


@dataclass(frozen=True)
class Progress:
    commitment: Commitment
    spent: Money
    cycles_done: int

    @property
    def remaining(self):
        r = self.commitment.minimum - self.spent
        return r if not r.is_negative() else Money.zero(r.currency)

    @property
    def percent(self):
        if not self.commitment.minimum:
            return Decimal(100)
        pct = self.spent.amount / self.commitment.minimum.amount * 100
        return pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    def projected_shortfall(self):
        if self.cycles_done == 0:
            return self.commitment.minimum
        per_cycle = self.spent.amount / self.cycles_done
        projected = per_cycle * self.commitment.cycles
        short = self.commitment.minimum.amount - projected
        cur = self.spent.currency
        return Money(round_to(max(short, Decimal(0)), cur), cur)


def parse_commitments(text, *, source="commitments.csv"):
    out = []
    for lineno, r in read_rows(text, required=("customer", "contract", "currency", "minimum",
                                               "start_cycle", "end_cycle"), source=source):
        parse_cycle(r["start_cycle"])
        parse_cycle(r["end_cycle"])
        if cycles_between(r["start_cycle"], r["end_cycle"]) < 0:
            raise ConfigError(f"line {lineno}: contract ends before it starts", source=source)
        minimum = dec(r["minimum"])
        if minimum <= 0:
            raise ConfigError(f"line {lineno}: minimum must be positive", source=source)
        out.append(Commitment(r["customer"].upper(), r["contract"], Money(minimum, r["currency"]),
                              r["start_cycle"], r["end_cycle"]))
    return out


def progress(commitment, history):
    """``history``: {cycle: Invoice} for the customer.  Invoices outside the term are ignored."""
    cur = commitment.minimum.currency
    spent = Money.zero(cur)
    done = 0
    for cycle, inv in sorted(history.items()):
        if not commitment.covers(cycle):
            continue
        if inv.currency != cur:
            raise ConfigError(f"{commitment.contract}: invoice {inv.number} is in {inv.currency}, contract in {cur}")
        spent = spent + (inv.subtotal - inv.discount_total - inv.late_fees)
        done += 1
    return Progress(commitment, spent, done)
