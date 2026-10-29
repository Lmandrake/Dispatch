"""Customer payments and their allocation to open receivables.

data/payments.csv lists money received, one row per payment:

    payment_id,customer,currency,amount,received,reference
    P-1001,C04,GBP,286.40,2026-03-09,KC-2026-01-C04

``payment_id`` is unique in the file, ``amount`` is positive and rounded to
the minor unit of ``currency``, ``received`` is a ``YYYY-MM-DD`` date and
``reference`` is free text the customer put on the transfer (it is shown on
the report but never used to pick the receivable: the allocation rule is the
same for everybody, see below).

Allocation rules
----------------

1. Payments are taken in order of ``received`` date, then ``payment_id``.
2. A payment is applied to the customer's *open* receivables of the same
   currency, oldest ``due`` date first (ties: invoice number).  A receivable
   whose ``paid_on`` is already set in receivables.csv is closed and takes
   nothing.
3. A payment smaller than the open amount is a *partial* allocation; the
   receivable stays open for the rest.  A payment larger than everything that
   is open is applied in full to what is open and the remainder becomes
   *unapplied cash*.
4. No currency conversion is done here.  A payment in a currency in which the
   customer has no open receivable is unapplied in full.

Nothing is rounded: all amounts are already in minor units, and allocation
only adds and subtracts them.
"""

from dataclasses import dataclass, field

from .csvutil import read_rows
from .errors import ConfigError
from .money import Money, dec
from .render.fmt import format_amount
from .timeutil import parse_date


@dataclass(frozen=True)
class Payment:
    payment_id: str
    customer: str
    amount: Money
    received: object      # date
    reference: str = ""


@dataclass(frozen=True)
class Allocation:
    """``amount`` of payment ``payment_id`` applied to receivable ``invoice``."""

    payment_id: str
    invoice: str
    amount: Money
    received: object


@dataclass(frozen=True)
class UnappliedCash:
    payment_id: str
    customer: str
    amount: Money
    received: object
    reason: str


@dataclass
class ReceivableStatus:
    """What happened to one receivable."""

    receivable: object
    allocations: list = field(default_factory=list)

    @property
    def currency(self):
        return self.receivable.amount.currency

    @property
    def closed_before(self):
        """True when receivables.csv already records the payment."""
        return self.receivable.paid_on is not None

    @property
    def allocated(self):
        total = Money.zero(self.currency)
        for a in self.allocations:
            total = total + a.amount
        return total

    @property
    def outstanding(self):
        if self.closed_before:
            return Money.zero(self.currency)
        return self.receivable.amount - self.allocated

    @property
    def state(self):
        if self.closed_before:
            return "paid"
        if not self.outstanding:
            return "settled"
        if self.allocations:
            return "partial"
        return "open"


@dataclass
class AllocationResult:
    statuses: list = field(default_factory=list)
    unapplied: list = field(default_factory=list)

    def status(self, invoice):
        for st in self.statuses:
            if st.receivable.invoice == invoice:
                return st
        raise KeyError(invoice)

    def allocations(self):
        return [a for st in self.statuses for a in st.allocations]

    def unapplied_total(self, customer, currency):
        total = Money.zero(currency)
        for u in self.unapplied:
            if u.customer == customer and u.amount.currency == currency:
                total = total + u.amount
        return total

    def outstanding_total(self, customer, currency):
        total = Money.zero(currency)
        for st in self.statuses:
            if st.receivable.customer == customer and st.currency == currency:
                total = total + st.outstanding
        return total


def parse_payments(text, *, source="payments.csv"):
    """Parse payments.csv text into a list of Payment in file order."""
    rows = read_rows(text, required=("payment_id", "customer", "currency", "amount", "received"),
                     optional=("reference",), source=source)
    out = []
    seen = set()
    for lineno, r in rows:
        pid = r["payment_id"]
        if pid in seen:
            raise ConfigError(f"line {lineno}: duplicate payment id {pid}", source=source)
        seen.add(pid)
        try:
            amount = Money(dec(r["amount"]), r["currency"])
            received = parse_date(r["received"])
        except (ValueError, TypeError) as e:
            raise ConfigError(f"line {lineno}: {e}", source=source) from None
        except ConfigError as e:
            raise ConfigError(f"line {lineno}: {e}", source=source) from None
        if amount.amount <= 0:
            raise ConfigError(f"line {lineno}: payment must be positive", source=source)
        if amount != amount.rounded():
            raise ConfigError(f"line {lineno}: amount {r['amount']} is finer than the minor unit of "
                              f"{amount.currency}", source=source)
        out.append(Payment(pid, r["customer"].upper(), amount, received, r["reference"]))
    return out


def allocate_payments(receivables, payments):
    """Apply ``payments`` to ``receivables`` by the rules in the module docstring.

    Returns an AllocationResult with one ReceivableStatus per receivable
    (same order as ``receivables``) and the unapplied cash.
    """
    statuses = [ReceivableStatus(r) for r in receivables]
    queues = {}
    for st in statuses:
        if not st.closed_before and st.receivable.amount:
            queues.setdefault((st.receivable.customer, st.currency), []).append(st)
    for q in queues.values():
        q.sort(key=lambda s: (s.receivable.due, s.receivable.invoice))
    result = AllocationResult(statuses)
    for pay in sorted(payments, key=lambda p: (p.received, p.payment_id)):
        cur = pay.amount.currency
        queue = queues.get((pay.customer, cur), [])
        left = pay.amount
        for st in queue:
            if not left:
                break
            room = st.outstanding
            if not room:
                continue
            take = left if left <= room else room
            st.allocations.append(Allocation(pay.payment_id, st.receivable.invoice, take, pay.received))
            left = left - take
        if left:
            if not queue:
                reason = f"no open {cur} receivable for {pay.customer}"
            else:
                reason = "overpayment"
            result.unapplied.append(UnappliedCash(pay.payment_id, pay.customer, left, pay.received, reason))
    return result


def render_allocation_report(result):
    """Text report: one row per receivable, then allocations and unapplied cash."""
    out = ["PAYMENT ALLOCATION", "=" * 72]
    out.append(f"{'invoice':<16}{'cust':<6}{'due':<12}{'amount':>12}{'applied':>12}{'open':>12}  state")
    for st in sorted(result.statuses, key=lambda s: (s.receivable.due, s.receivable.invoice)):
        r = st.receivable
        applied = r.amount if st.closed_before else st.allocated
        out.append(f"{r.invoice:<16}{r.customer:<6}{r.due.isoformat():<12}"
                   f"{format_amount(r.amount):>12}{format_amount(applied):>12}"
                   f"{format_amount(st.outstanding):>12}  {st.state} {r.amount.currency}")
    allocs = result.allocations()
    out.append("-" * 72)
    out.append("Allocations")
    if not allocs:
        out.append("  none")
    for a in sorted(allocs, key=lambda a: (a.received, a.payment_id, a.invoice)):
        out.append(f"  {a.payment_id:<10}{a.received.isoformat():<12}-> {a.invoice:<16}"
                   f"{format_amount(a.amount):>12} {a.amount.currency}")
    out.append("Unapplied cash")
    if not result.unapplied:
        out.append("  none")
    for u in sorted(result.unapplied, key=lambda u: (u.customer, u.received, u.payment_id)):
        out.append(f"  {u.payment_id:<10}{u.customer:<6}{format_amount(u.amount):>12} "
                   f"{u.amount.currency}  {u.reason}")
    return "\n".join(out) + "\n"
