"""Dunning: what happens to unpaid invoices (docs/DUNNING.md).

data/receivables.csv lists issued invoices and their payments:

    invoice,customer,currency,amount,due,paid_on
    KC-2026-01-C05,C05,USD,412.30,2026-03-03,

The schedule (data/dunning.toml) is a list of steps, each ``days`` after the
due date:

    [[steps]]  days = 7   action = "reminder"
    [[steps]]  days = 21  action = "late_fee"   percent = "1.5"  minimum = "5.00"  currency = "USD"
    [[steps]]  days = 45  action = "suspend"

``evaluate(receivables, schedule, as_of)`` returns, per open invoice, the
steps that have been reached on ``as_of`` (docs/DUNNING.md).  A late fee is ``percent`` of the open amount, rounded
half-up to the invoice currency, but at least ``minimum`` (converted to the
invoice currency at the rate of the step date, then rounded half-up).
Fees are charged on the customer's next invoice and are neither taxed nor
discounted.
"""

import tomllib
from dataclasses import dataclass, field
from datetime import timedelta

from .csvutil import read_rows
from .errors import ConfigError, DunningError
from .money import Money, dec, round_to
from .timeutil import parse_date

ACTIONS = ("reminder", "late_fee", "suspend")


@dataclass(frozen=True)
class Step:
    days: int
    action: str
    percent: object = None
    minimum: object = None
    currency: str = "USD"


@dataclass(frozen=True)
class Receivable:
    invoice: str
    customer: str
    amount: Money
    due: object
    paid_on: object = None

    def open_on(self, day):
        return self.paid_on is None or self.paid_on > day


@dataclass
class DunningState:
    receivable: Receivable
    reached: list = field(default_factory=list)   # (Step, date)
    fee: Money = None

    @property
    def suspended(self):
        return any(s.action == "suspend" for s, _ in self.reached)

    @property
    def reminders(self):
        return sum(1 for s, _ in self.reached if s.action == "reminder")


def parse_schedule(text, *, source="dunning.toml"):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}", source=source) from None
    steps = []
    for i, raw in enumerate(data.get("steps", [])):
        action = raw.get("action")
        if action not in ACTIONS:
            raise ConfigError(f"step {i + 1}: action must be one of {', '.join(ACTIONS)}", source=source)
        days = raw.get("days")
        if not isinstance(days, int) or days < 0:
            raise ConfigError(f"step {i + 1}: days must be a non-negative integer", source=source)
        if action == "late_fee":
            if "percent" not in raw:
                raise ConfigError(f"step {i + 1}: late_fee needs percent", source=source)
            steps.append(Step(days, action, dec(str(raw["percent"])), dec(str(raw.get("minimum", "0"))),
                              str(raw.get("currency", "USD"))))
        else:
            steps.append(Step(days, action))
    if [s.days for s in steps] != sorted(s.days for s in steps):
        raise ConfigError("steps must be in increasing order of days", source=source)
    if sum(1 for s in steps if s.action == "late_fee") > 1:
        raise ConfigError("at most one late_fee step", source=source)
    return steps


def parse_receivables(text, *, source="receivables.csv"):
    out = []
    for lineno, r in read_rows(text, required=("invoice", "customer", "currency", "amount", "due"),
                               optional=("paid_on",), source=source):
        due = parse_date(r["due"])
        paid = parse_date(r["paid_on"]) if r["paid_on"] else None
        amount = Money(dec(r["amount"]), r["currency"])
        if amount.is_negative():
            raise ConfigError(f"line {lineno}: negative receivable", source=source)
        out.append(Receivable(r["invoice"], r["customer"].upper(), amount, due, paid))
    return out


def late_fee(step, receivable, converter, on):
    cur = receivable.amount.currency
    fee = Money(round_to(receivable.amount.amount * step.percent / 100, cur), cur)
    if step.minimum:
        floor = converter.convert(Money(step.minimum, step.currency), cur, on).rounded()
        if fee < floor:
            fee = floor
    return fee


def evaluate(receivables, schedule, as_of, converter, since=None):
    """Dunning state of every receivable on ``as_of``.

    ``since`` is the dunning date of the previous cycle (late fees billed
    then are not billed again).
    """
    states = []
    for rec in receivables:
        st = DunningState(rec)
        for step in schedule:
            when = rec.due + timedelta(days=step.days)
            if as_of < when:
                break
            if not rec.open_on(when):
                break
            st.reached.append((step, when))
            if step.action == "late_fee" and (since is None or when > since):
                st.fee = late_fee(step, rec, converter, when)
        if st.reached:
            states.append(st)
    return states


def late_fees_by_customer(states):
    """customer id -> [(description, Money)] for the next invoice."""
    out = {}
    for st in states:
        if st.fee is not None:
            out.setdefault(st.receivable.customer, []).append(
                (f"Late fee on {st.receivable.invoice}", st.fee))
    return out


def suspended_customers(states):
    return sorted({st.receivable.customer for st in states if st.suspended})


def render_dunning(states):
    if not states:
        return "No overdue invoices.\n"
    lines = [f"{'invoice':<18}{'customer':<10}{'open':>14}  steps"]
    for st in sorted(states, key=lambda s: s.receivable.invoice):
        r = st.receivable
        steps = ", ".join(f"{s.action}@{d.isoformat()}" for s, d in st.reached)
        lines.append(f"{r.invoice:<18}{r.customer:<10}{str(r.amount.rounded()):>14}  {steps}")
    return "\n".join(lines) + "\n"


def check_paid_before_due(receivables):
    bad = [r for r in receivables if r.paid_on is not None and r.paid_on < r.due - timedelta(days=365)]
    if bad:
        raise DunningError(f"implausible payment dates on {', '.join(r.invoice for r in bad)}")
