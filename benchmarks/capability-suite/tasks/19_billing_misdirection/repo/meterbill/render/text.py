"""Plain-text invoice (the source the PDF service typesets, 72 columns)."""

from ..money import Money
from .fmt import format_amount, format_qty, format_unit_price

WIDTH = 72
AMT = 14


def _row(left, amount):
    return f"{left[: WIDTH - AMT - 1]:<{WIDTH - AMT}}{amount:>{AMT}}"


def _rule(ch="-"):
    return ch * WIDTH


def render_text(inv):
    c = inv.customer
    cur = inv.currency
    out = []
    out.append(f"INVOICE {inv.number}")
    out.append(_rule("="))
    out.append(f"Bill to:  {c.name} ({c.id})")
    if c.tax_id:
        out.append(f"Tax id:   {c.tax_id}")
    out.append(f"Period:   {inv.period.label()} ({inv.period.tz})")
    out.append(f"Issued:   {inv.issued.isoformat()}    Due: {inv.due.isoformat()}")
    out.append(f"Currency: {cur}")
    out.append(_rule())
    for ln in inv.lines:
        if ln.kind == "usage":
            left = f"{ln.description}: {format_qty(ln.quantity, ln.precision)} {ln.unit}"
        else:
            left = ln.description
        out.append(_row(left, format_amount(ln.amount)))
        for d in ln.details:
            out.append(_row(f"    {d.label}: {format_qty(d.quantity, d.precision)} @ {format_unit_price(d.unit_price)}", ""))
    out.append(_rule())
    out.append(_row("Subtotal", format_amount(inv.subtotal)))
    for d in inv.discounts:
        out.append(_row(f"Discount {d.coupon.describe()}", format_amount(-d.amount)))
    tax = inv.tax
    if tax.reverse_charged:
        out.append(_row(f"{tax.rule.label} (reverse charge)", format_amount(tax.tax)))
    else:
        out.append(_row(f"{tax.rule.label} {tax.rule.percent()} on {format_amount(tax.taxable)}", format_amount(tax.tax)))
    out.append(_rule())
    out.append(_row(f"TOTAL {cur}", format_amount(inv.total)))
    for use in inv.credits:
        if use.applied:
            out.append(_row(f"Credit {use.grant.grant_id} (left: {format_amount(use.remaining)} {use.remaining.currency})",
                            format_amount(-use.applied)))
    if inv.credits and inv.credit_total:
        out.append(_row(f"AMOUNT DUE {cur}", format_amount(inv.amount_due)))
    out.append(_rule("="))
    for note in inv.notes:
        out.append(note)
    return "\n".join(out) + "\n"


def render_summary_line(inv):
    return f"{inv.number} {inv.customer.id} {inv.currency} {format_amount(inv.amount_due)}"


def zero(cur):
    return Money.zero(cur)
