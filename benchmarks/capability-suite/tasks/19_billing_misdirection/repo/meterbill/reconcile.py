"""Month-end reconciliation report (docs/RECONCILIATION.md).

For one cycle, per customer:

    records   usage records of the customer that fall in the billing period
    billed    of those, the ones charged on the invoice
    unbilled  in the period but outside any subscription
    rejected  feed rows that were rejected and name this customer
    invoiced  the invoice total, converted to USD at the rate of the
              period's last day and rounded half-up
    due       the amount due in USD, likewise

and a totals row.  ``feed_balance`` checks that every ingested record of the
cycle's customers is either billed, unbilled, or outside the period.
"""

from dataclasses import dataclass

from .fx import REFERENCE
from .money import Money


@dataclass(frozen=True)
class ReconRow:
    customer: str
    currency: str
    records: int
    billed: int
    unbilled: int
    rejected: int
    invoiced_usd: Money
    due_usd: Money


def reconcile(invoices, ingested, converter):
    rows = []
    reject_counts = {}
    for rj in ingested.rejects:
        cid = _reject_customer(rj)
        if cid:
            reject_counts[cid] = reject_counts.get(cid, 0) + 1
    for inv in invoices:
        counts = inv.usage_counts
        records = counts["billed"] + counts["unbilled"]
        inv_usd = converter.convert(inv.total, REFERENCE, inv.rate_day).rounded()
        due_usd = converter.convert(inv.amount_due, REFERENCE, inv.rate_day).rounded()
        rows.append(ReconRow(inv.customer.id, inv.currency, records, counts["billed"], counts["unbilled"],
                             reject_counts.get(inv.customer.id, 0), inv_usd, due_usd))
    return rows


def _reject_customer(reject):
    raw = reject.raw
    for token in raw.replace(",", " ").replace('"', " ").split():
        if token.startswith("cust="):
            token = token[5:]
        if len(token) >= 2 and token[0] == "C" and token[1:].isdigit():
            return token
    return None


def feed_balance(invoices, ingested):
    """Records per customer that are unaccounted for (should be empty)."""
    problems = {}
    for inv in invoices:
        cid = inv.customer.id
        n = len(ingested.for_customer(cid))
        c = inv.usage_counts
        if c["billed"] + c["unbilled"] + c["outside"] != n:
            problems[cid] = n - (c["billed"] + c["unbilled"] + c["outside"])
    return problems


def render_recon(cycle, rows, ingested):
    head = f"Reconciliation {cycle}"
    lines = [head, "=" * 78,
             f"{'customer':<9}{'cur':<5}{'records':>8}{'billed':>8}{'unbilled':>9}{'rejected':>9}"
             f"{'invoiced USD':>15}{'due USD':>15}"]
    tot_inv = Money.zero(REFERENCE)
    tot_due = Money.zero(REFERENCE)
    n = b = u = rj = 0
    for r in rows:
        lines.append(f"{r.customer:<9}{r.currency:<5}{r.records:>8}{r.billed:>8}{r.unbilled:>9}{r.rejected:>9}"
                     f"{_amt(r.invoiced_usd):>15}{_amt(r.due_usd):>15}")
        tot_inv = tot_inv + r.invoiced_usd
        tot_due = tot_due + r.due_usd
        n += r.records
        b += r.billed
        u += r.unbilled
        rj += r.rejected
    lines.append("-" * 78)
    lines.append(f"{'TOTAL':<14}{n:>8}{b:>8}{u:>9}{rj:>9}{_amt(tot_inv):>15}{_amt(tot_due):>15}")
    lines.append("")
    lines.append(f"feed files: {len(ingested.files)}   records: {len(ingested.records)}   "
                 f"replays dropped: {ingested.replays}   rejected rows: {len(ingested.rejects)}")
    for rj_ in ingested.rejects:
        lines.append(f"  rejected {rj_}")
    return "\n".join(lines) + "\n"


def _amt(m):
    from .render.fmt import format_amount
    return format_amount(m)
