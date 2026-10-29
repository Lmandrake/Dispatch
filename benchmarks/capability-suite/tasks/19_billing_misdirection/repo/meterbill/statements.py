"""Customer account statements (docs/INVOICES.md, "Statements").

A statement lists, for one customer, the open receivables from
receivables.csv plus the invoice of the current cycle, oldest first, with a
running balance in the customer's currency.  Receivables in another currency
(customers who changed currency) are converted at the rate of the statement
date and rounded half-up.  Paid receivables are left out.
"""

from dataclasses import dataclass, field

from .money import Money


@dataclass(frozen=True)
class StatementRow:
    ref: str
    date: object
    due: object
    amount: Money
    balance: Money


@dataclass
class Statement:
    customer: object
    as_of: object
    currency: str
    rows: list = field(default_factory=list)

    @property
    def balance(self):
        return self.rows[-1].balance if self.rows else Money.zero(self.currency)

    def overdue(self):
        return [r for r in self.rows if r.due < self.as_of]


def statement(customer, receivables, invoice, converter):
    cur = customer.currency
    as_of = invoice.issued
    items = []
    for r in receivables:
        if r.customer != customer.id or not r.open_on(as_of):
            continue
        amt = r.amount if r.amount.currency == cur else converter.convert(r.amount, cur, as_of).rounded()
        items.append((r.due, r.invoice, r.due, amt))
    items.append((invoice.due, invoice.number, invoice.due, invoice.amount_due))
    items.sort(key=lambda t: (t[0], t[1]))
    st = Statement(customer, as_of, cur)
    bal = Money.zero(cur)
    for _, ref, due, amt in items:
        bal = bal + amt
        st.rows.append(StatementRow(ref, due, due, amt, bal))
    return st


def render_statement(st):
    from .render.fmt import format_amount
    c = st.customer
    out = [f"STATEMENT {c.name} ({c.id}) as of {st.as_of.isoformat()}",
           f"{'ref':<20}{'due':<12}{'amount':>14}{'balance':>14}"]
    for r in st.rows:
        flag = " *" if r.due < st.as_of else ""
        out.append(f"{r.ref:<20}{r.due.isoformat():<12}{format_amount(r.amount):>14}{format_amount(r.balance):>14}{flag}")
    out.append(f"{'BALANCE ' + st.currency:<46}{format_amount(st.balance):>14}")
    if st.overdue():
        out.append("* overdue")
    return "\n".join(out) + "\n"
