"""Accounts-receivable aging (docs/DUNNING.md, "Aging").

Open receivables are bucketed by days past due on an ``as_of`` date:

    current   not yet due (as_of <= due)
    1-30      1 to 30 days past due
    31-60
    61-90
    90+

Amounts are converted to USD at the rate of ``as_of`` and rounded half-up
per receivable before bucketing, so bucket totals equal the sum of the
printed rows.
"""

from dataclasses import dataclass

from .fx import REFERENCE
from .money import Money

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def bucket_for(days_late):
    if days_late <= 0:
        return "current"
    if days_late <= 30:
        return "1-30"
    if days_late <= 60:
        return "31-60"
    if days_late <= 90:
        return "61-90"
    return "90+"


@dataclass(frozen=True)
class AgingRow:
    invoice: str
    customer: str
    amount: Money
    usd: Money
    days_late: int
    bucket: str


def aging(receivables, as_of, converter):
    rows = []
    for r in receivables:
        if not r.open_on(as_of):
            continue
        late = (as_of - r.due).days
        usd = converter.convert(r.amount, REFERENCE, as_of).rounded()
        rows.append(AgingRow(r.invoice, r.customer, r.amount, usd, late, bucket_for(late)))
    rows.sort(key=lambda a: (-a.days_late, a.invoice))
    return rows


def bucket_totals(rows):
    totals = {b: Money.zero(REFERENCE) for b in BUCKETS}
    for r in rows:
        totals[r.bucket] = totals[r.bucket] + r.usd
    return totals


def render_aging(rows, as_of):
    from .render.fmt import format_amount
    out = [f"AR aging as of {as_of.isoformat()} (USD)",
           f"{'invoice':<18}{'customer':<10}{'days':>6}  {'bucket':<8}{'open':>16}{'USD':>14}"]
    for r in rows:
        out.append(f"{r.invoice:<18}{r.customer:<10}{r.days_late:>6}  {r.bucket:<8}"
                   f"{format_amount(r.amount) + ' ' + r.amount.currency:>16}{format_amount(r.usd):>14}")
    out.append("")
    totals = bucket_totals(rows)
    out.append("  ".join(f"{b}: {format_amount(totals[b])}" for b in BUCKETS))
    return "\n".join(out) + "\n"
