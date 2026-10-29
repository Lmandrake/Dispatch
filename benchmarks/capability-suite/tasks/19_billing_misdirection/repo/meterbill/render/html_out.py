"""HTML invoice for the e-mail body and the portal preview.

A self-contained document (inline CSS, no scripts).  Like every renderer it
only formats Invoice fields; all text is HTML-escaped.
"""

from html import escape

from .fmt import format_amount, format_qty, format_unit_price

CSS = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1d1d1f; margin: 2em; }
h1 { font-size: 1.4em; margin-bottom: 0.2em; }
table { border-collapse: collapse; width: 100%; max-width: 46em; }
td, th { padding: 0.25em 0.5em; vertical-align: top; }
td.amt, th.amt { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.detail td { color: #6e6e73; font-size: 0.9em; padding-left: 2em; }
tr.sum td { border-top: 1px solid #d2d2d7; }
tr.total td { border-top: 2px solid #1d1d1f; font-weight: 600; }
p.note { color: #6e6e73; font-size: 0.9em; }
""".strip()


def _tr(cells, cls=None):
    attr = f' class="{cls}"' if cls else ""
    return f"<tr{attr}>" + "".join(cells) + "</tr>"


def _td(text, amt=False):
    return f'<td class="amt">{escape(text)}</td>' if amt else f"<td>{escape(text)}</td>"


def render_html(inv):
    c = inv.customer
    cur = inv.currency
    rows = []
    for ln in inv.lines:
        if ln.kind == "usage":
            desc = f"{ln.description}: {format_qty(ln.quantity, ln.precision)} {ln.unit}"
        else:
            desc = ln.description
        rows.append(_tr([_td(desc), _td(format_amount(ln.amount), True)]))
        for d in ln.details:
            rows.append(_tr([_td(f"{d.label}: {format_qty(d.quantity, d.precision)} @ {format_unit_price(d.unit_price)}"),
                             _td("", True)], "detail"))
    rows.append(_tr([_td("Subtotal"), _td(format_amount(inv.subtotal), True)], "sum"))
    for d in inv.discounts:
        rows.append(_tr([_td(f"Discount {d.coupon.describe()}"), _td(format_amount(-d.amount), True)]))
    tax = inv.tax
    if tax.reverse_charged:
        rows.append(_tr([_td(f"{tax.rule.label} (reverse charge)"), _td(format_amount(tax.tax), True)]))
    else:
        rows.append(_tr([_td(f"{tax.rule.label} {tax.rule.percent()} on {format_amount(tax.taxable)}"),
                         _td(format_amount(tax.tax), True)]))
    rows.append(_tr([_td(f"Total {cur}"), _td(format_amount(inv.total), True)], "total"))
    for use in inv.credits:
        if use.applied:
            rows.append(_tr([_td(f"Credit {use.grant.grant_id}"), _td(format_amount(-use.applied), True)]))
    if inv.credit_total:
        rows.append(_tr([_td(f"Amount due {cur}"), _td(format_amount(inv.amount_due), True)], "total"))
    notes = "".join(f'<p class="note">{escape(n)}</p>' for n in inv.notes)
    head = (f"<h1>Invoice {escape(inv.number)}</h1>"
            f"<p>{escape(c.name)} ({escape(c.id)})<br>"
            f"Period {escape(inv.period.label())} ({escape(inv.period.tz)})<br>"
            f"Issued {inv.issued.isoformat()}, due {inv.due.isoformat()}</p>")
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>Invoice {escape(inv.number)}</title><style>{CSS}</style></head><body>"
            f"{head}<table>{''.join(rows)}</table>{notes}</body></html>\n")
