"""Dict forms of billing objects for the customer-portal API.

Conventions (docs/OPERATIONS.md, "Portal"):

* Every amount is a string in plain machine form (``"1234.50"``, no
  grouping) next to a ``currency`` code; a quantity or a unit price is the
  Decimal's text, normalised so that ``Decimal("1E+3")`` prints ``"1000"``.
* Dates are ISO ``YYYY-MM-DD`` strings; instants are ISO UTC with ``Z``.
* Keys are always present (``null`` for "no value"), lists are always lists.
* Nothing here rounds or computes money: every figure is a field of the
  object being serialized.
"""

from ..render.fmt import plain_amount
from ..timeutil import format_instant


def amount_str(money):
    """Plain machine text of a Money amount: ``'-1234.50'``."""
    return plain_amount(money)


def decimal_str(value):
    """Decimal text without exponent or trailing zeros: ``'1000'``, ``'0.0004'``."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text


def customer_dict(customer):
    return {
        "id": customer.id,
        "name": customer.name,
        "timezone": customer.timezone,
        "anchor_day": customer.anchor_day,
        "currency": customer.currency,
        "jurisdiction": customer.jurisdiction,
        "business": customer.is_business,
        "email": customer.email or None,
        "terms_days": customer.terms_days,
        "status": customer.status,
    }


def _line_dict(ln):
    return {
        "kind": ln.kind,
        "description": ln.description,
        "quantity": decimal_str(ln.quantity),
        "unit": ln.unit,
        "amount": amount_str(ln.amount),
        "plan": ln.plan or None,
        "metric": ln.metric or None,
        "from": ln.start.isoformat() if ln.start else None,
        "to": ln.end.isoformat() if ln.end else None,
        "details": [{"label": d.label, "quantity": decimal_str(d.quantity),
                     "unit_price": decimal_str(d.unit_price)} for d in ln.details],
    }


def invoice_summary_dict(inv):
    """The short form used in listings."""
    return {
        "number": inv.number,
        "customer": inv.customer.id,
        "cycle": inv.cycle,
        "issued": inv.issued.isoformat(),
        "due": inv.due.isoformat(),
        "currency": inv.currency,
        "total": amount_str(inv.total),
        "amount_due": amount_str(inv.amount_due),
    }


def invoice_dict(inv):
    """The full invoice document."""
    doc = invoice_summary_dict(inv)
    doc.update({
        "period": {"start": inv.period.start.isoformat(), "last_day": inv.period.last_day.isoformat(),
                   "timezone": inv.period.tz},
        "lines": [_line_dict(ln) for ln in inv.lines],
        "subtotal": amount_str(inv.subtotal),
        "discounts": [{"description": d.coupon.describe(), "amount": amount_str(d.amount)}
                      for d in inv.discounts],
        "discount_total": amount_str(inv.discount_total),
        "tax": {"label": inv.tax.rule.label, "amount": amount_str(inv.tax.tax),
                "taxable": amount_str(inv.tax.taxable), "reverse_charged": inv.tax.reverse_charged},
        "late_fees": amount_str(inv.late_fees),
        "credit_total": amount_str(inv.credit_total),
        "notes": list(inv.notes),
    })
    return doc


def _tier_dict(tier):
    return {"up_to": decimal_str(tier.up_to), "unit_price": decimal_str(tier.unit_price),
            "flat_fee": decimal_str(tier.flat_fee)}


def _charge_dict(charge, metrics):
    metric = metrics.get(charge.metric)
    p = charge.price
    return {
        "metric": charge.metric,
        "metric_name": metric.name,
        "unit": metric.unit,
        "model": p.model,
        "unit_price": decimal_str(p.unit_price) if p.model in ("per_unit", "package", "flat") else None,
        "package_size": decimal_str(p.package_size) if p.model == "package" else None,
        "included": decimal_str(p.included),
        "tiers": [_tier_dict(t) for t in p.tiers],
        "description": charge.description or None,
    }


def plan_dict(plan, metrics):
    """A catalogue plan; ``metrics`` is the catalogue's MetricSet."""
    return {
        "id": plan.id,
        "name": plan.name,
        "currency": plan.currency,
        "base_fee": decimal_str(plan.base_fee),
        "legacy": plan.legacy,
        "charges": [_charge_dict(c, metrics) for c in plan.charges],
    }


def usage_summary_dict(customer_id, records, metrics, period=None):
    """Per-metric billed quantity of ``records`` (optionally only inside ``period``).

    The quantity uses the metric's own aggregation (sum, max or last).
    """
    by_metric = {}
    for r in records:
        if r.customer != customer_id:
            continue
        if period is not None and not period.contains(r.at):
            continue
        by_metric.setdefault(r.metric, []).append(r)
    out = []
    for metric in metrics:
        recs = by_metric.get(metric.id)
        if not recs:
            continue
        out.append({
            "metric": metric.id,
            "name": metric.name,
            "unit": metric.unit,
            "aggregation": metric.aggregation,
            "quantity": decimal_str(metric.aggregate(recs)),
            "records": len(recs),
            "first": format_instant(min(r.at for r in recs)),
            "last": format_instant(max(r.at for r in recs)),
        })
    return {"customer": customer_id, "period": None if period is None else {
        "start": period.start.isoformat(), "last_day": period.last_day.isoformat()}, "metrics": out}
