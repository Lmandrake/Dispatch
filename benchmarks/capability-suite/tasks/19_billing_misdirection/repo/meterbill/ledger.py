"""General-ledger journal export (docs/LEDGER.md).

Each invoice becomes one balanced journal entry in the invoice currency:

    Dr 1200 Accounts receivable        total
    Dr 4900 Discounts given            each coupon
    Cr 4100 Subscription revenue       base lines, per plan
    Cr 4200 Usage revenue              usage lines, per metric
    Cr 4300 Late fee income            fee lines
    Cr 2300 Tax payable                tax (by jurisdiction)

and, when prepaid credit is used, a second entry:

    Dr 2400 Customer credit liability  credit applied
    Cr 1200 Accounts receivable        credit applied

Every entry balances to the minor unit; ``check_balanced`` asserts it.
The export is a CSV with one row per posting, in the order above.
"""

from dataclasses import dataclass, field

from .csvutil import write_rows
from .money import Money

ACCOUNTS = {
    "1200": "Accounts receivable",
    "2300": "Tax payable",
    "2400": "Customer credit liability",
    "4100": "Subscription revenue",
    "4200": "Usage revenue",
    "4300": "Late fee income",
    "4900": "Discounts given",
}


@dataclass(frozen=True)
class Posting:
    account: str
    debit: Money
    credit: Money
    memo: str = ""

    @property
    def net(self):
        return self.debit - self.credit


@dataclass
class JournalEntry:
    ref: str
    date: object
    currency: str
    postings: list = field(default_factory=list)

    def dr(self, account, amount, memo=""):
        if amount:
            self.postings.append(Posting(account, amount, Money.zero(self.currency), memo))

    def cr(self, account, amount, memo=""):
        if amount:
            self.postings.append(Posting(account, Money.zero(self.currency), amount, memo))

    def totals(self):
        d = Money.zero(self.currency)
        c = Money.zero(self.currency)
        for p in self.postings:
            d = d + p.debit
            c = c + p.credit
        return d, c

    def balanced(self):
        d, c = self.totals()
        return d == c


class UnbalancedEntry(ValueError):
    pass


def check_balanced(entry):
    d, c = entry.totals()
    if d != c:
        raise UnbalancedEntry(f"{entry.ref}: debits {d} != credits {c}")
    return entry


def invoice_entries(inv):
    """Journal entries for one invoice (one or two)."""
    cur = inv.currency
    e = JournalEntry(inv.number, inv.issued, cur)
    e.dr("1200", inv.total, inv.customer.id)
    for d in inv.discounts:
        e.dr("4900", d.amount, d.coupon.code)
    by_plan = {}
    by_metric = {}
    fees = Money.zero(cur)
    for ln in inv.lines:
        if ln.kind == "base":
            by_plan[ln.plan] = by_plan.get(ln.plan, Money.zero(cur)) + ln.amount
        elif ln.kind == "usage":
            by_metric[ln.metric] = by_metric.get(ln.metric, Money.zero(cur)) + ln.amount
        else:
            fees = fees + ln.amount
    for plan in by_plan:
        e.cr("4100", by_plan[plan], plan)
    for metric in sorted(by_metric):
        e.cr("4200", by_metric[metric], metric)
    e.cr("4300", fees, "late fees")
    e.cr("2300", inv.tax.tax, inv.tax.rule.code)
    entries = [check_balanced(e)]
    if inv.credit_total:
        c = JournalEntry(inv.number + "/CR", inv.issued, cur)
        c.dr("2400", inv.credit_total, ",".join(u.grant.grant_id for u in inv.credits if u.applied))
        c.cr("1200", inv.credit_total, inv.customer.id)
        entries.append(check_balanced(c))
    return entries


def journal(invoices):
    out = []
    for inv in invoices:
        out.extend(invoice_entries(inv))
    return out


def trial_balance(entries):
    """account -> {currency: net Money (debit positive)}."""
    tb = {}
    for e in entries:
        for p in e.postings:
            per = tb.setdefault(p.account, {})
            per[e.currency] = per.get(e.currency, Money.zero(e.currency)) + p.net
    return tb


def render_journal_csv(entries):
    from .render.fmt import plain_amount
    rows = []
    for e in entries:
        for p in e.postings:
            rows.append((e.ref, e.date.isoformat(), p.account, ACCOUNTS[p.account],
                         plain_amount(p.debit) if p.debit else "",
                         plain_amount(p.credit) if p.credit else "",
                         e.currency, p.memo))
    return write_rows(("ref", "date", "account", "account_name", "debit", "credit", "currency", "memo"), rows)
