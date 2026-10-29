"""JSON invoice for the customer portal.

Amounts are strings (never floats) in plain form; dates are ISO; keys are
sorted and the document is indented by 2 so goldens diff cleanly.
"""

import json

from .fmt import plain_amount


def _q(q):
    return f"{q.normalize():f}"


def invoice_dict(inv):
    return {
        "number": inv.number,
        "customer": {"id": inv.customer.id, "name": inv.customer.name, "tax_id": inv.customer.tax_id or None},
        "period": {
            "cycle": inv.cycle,
            "start": inv.period.start.isoformat(),
            "end": inv.period.last_day.isoformat(),
            "timezone": inv.period.tz,
        },
        "issued": inv.issued.isoformat(),
        "due_date": inv.due.isoformat(),
        "currency": inv.currency,
        "lines": [
            {
                "kind": ln.kind,
                "description": ln.description,
                "quantity": _q(ln.quantity),
                "unit": ln.unit,
                "amount": plain_amount(ln.amount),
                **({"plan": ln.plan} if ln.plan else {}),
                **({"metric": ln.metric} if ln.metric else {}),
            }
            for ln in inv.lines
        ],
        "subtotal": plain_amount(inv.subtotal),
        "discounts": [{"coupon": d.coupon.code, "amount": plain_amount(d.amount)} for d in inv.discounts],
        "tax": {
            "jurisdiction": inv.tax.rule.code,
            "rate": f"{inv.tax.rate.normalize():f}",
            "taxable": plain_amount(inv.tax.taxable),
            "amount": plain_amount(inv.tax.tax),
            "reverse_charge": inv.tax.reverse_charged,
        },
        "late_fees": plain_amount(inv.late_fees),
        "total": plain_amount(inv.total),
        "credits": [
            {"grant": u.grant.grant_id, "applied": plain_amount(u.applied),
             "remaining": plain_amount(u.remaining), "remaining_currency": u.remaining.currency}
            for u in inv.credits if u.applied
        ],
        "amount_due": plain_amount(inv.amount_due),
        "notes": list(inv.notes),
    }


def render_json(inv):
    return json.dumps(invoice_dict(inv), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
