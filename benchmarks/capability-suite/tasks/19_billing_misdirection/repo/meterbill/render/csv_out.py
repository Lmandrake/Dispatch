"""CSV invoice for the ERP import.

One row per line, then summary rows.  Columns:

    invoice,customer,kind,description,quantity,unit,amount,currency

Amounts are plain (no grouping, fixed minor-unit digits).  Summary rows have
kind ``subtotal``, ``discount`` (one per coupon, negative), ``tax``, ``fee``
(late fees), ``total``, ``credit`` (one per grant used, negative) and
``due``.
"""

from ..csvutil import write_rows
from .fmt import plain_amount

HEADER = ("invoice", "customer", "kind", "description", "quantity", "unit", "amount", "currency")


def _qty(q):
    return f"{q.normalize():f}" if q == q else ""


def render_csv(inv):
    cur = inv.currency
    n, cid = inv.number, inv.customer.id
    rows = []
    for ln in inv.lines:
        if ln.kind == "fee":
            continue
        rows.append((n, cid, ln.kind, ln.description, _qty(ln.quantity), ln.unit, plain_amount(ln.amount), cur))
    rows.append((n, cid, "subtotal", "", "", "", plain_amount(inv.subtotal), cur))
    for d in inv.discounts:
        rows.append((n, cid, "discount", d.coupon.code, "", "", plain_amount(-d.amount), cur))
    rows.append((n, cid, "tax", f"{inv.tax.rule.code} {inv.tax.rule.percent()}", "", "", plain_amount(inv.tax.tax), cur))
    for ln in inv.lines:
        if ln.kind == "fee":
            rows.append((n, cid, "fee", ln.description, "1", "fee", plain_amount(ln.amount), cur))
    rows.append((n, cid, "total", "", "", "", plain_amount(inv.total), cur))
    for use in inv.credits:
        if use.applied:
            rows.append((n, cid, "credit", use.grant.grant_id, "", "", plain_amount(-use.applied), cur))
    rows.append((n, cid, "due", "", "", "", plain_amount(inv.amount_due), cur))
    return write_rows(HEADER, rows)
