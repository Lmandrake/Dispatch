"""The portal request router: ``handle(path, query, run) -> (status, dict)``.

Routes (all GET, all JSON):

    /customers                     list, paginated
    /customers/<id>                one customer
    /customers/<id>/invoices       that customer's invoices of the run, paginated
    /customers/<id>/usage          usage summary of the run's cycle
    /invoices/<number>             one invoice in full
    /plans                         the catalogue (``?legacy=1`` includes legacy plans)
    /plans/<id>                    one plan

``run`` is a pipeline.BillingRun.  Statuses: 200, 400 (bad query value), 404
(unknown path, customer, invoice or plan).  Every error body is
``{"error": <code>, "message": <text>}``.  Ids are matched case-insensitively
for customers and exactly for invoices and plans.  A trailing slash is
ignored.  ``handle`` never raises for client mistakes.
"""

from ..errors import UnknownCustomer, UnknownPlan
from .pagination import BadRequest, paginate
from .serializers import (customer_dict, invoice_dict, invoice_summary_dict, plan_dict,
                          usage_summary_dict)

_TRUE = ("1", "true", "yes")


def error(status, code, message):
    return status, {"error": code, "message": message}


def _not_found(what):
    return error(404, "not_found", f"{what} not found")


def _customer(run, cid):
    try:
        return run.dataset.customers.get(cid.upper())
    except UnknownCustomer:
        return None


def _customers(run, query):
    page = paginate([customer_dict(c) for c in run.dataset.customers], query)
    return 200, page.to_dict("customers")


def _customer_one(run, query, cid):
    cust = _customer(run, cid)
    return _not_found(f"customer {cid}") if cust is None else (200, customer_dict(cust))


def _customer_invoices(run, query, cid):
    cust = _customer(run, cid)
    if cust is None:
        return _not_found(f"customer {cid}")
    invs = sorted((i for i in run.invoices if i.customer.id == cust.id), key=lambda i: i.number)
    page = paginate([invoice_summary_dict(i) for i in invs], query)
    return 200, page.to_dict("invoices")


def _customer_usage(run, query, cid):
    cust = _customer(run, cid)
    if cust is None:
        return _not_found(f"customer {cid}")
    invs = [i for i in run.invoices if i.customer.id == cust.id]
    period = invs[0].period if invs else None
    return 200, usage_summary_dict(cust.id, run.ingested.records, run.dataset.catalog.metrics, period)


def _invoice(run, query, number):
    for inv in run.invoices:
        if inv.number == number:
            return 200, invoice_dict(inv)
    return _not_found(f"invoice {number}")


def _plans(run, query):
    cat = run.dataset.catalog
    with_legacy = str(query.get("legacy", "")).lower() in _TRUE
    plans = [plan_dict(p, cat.metrics) for p in cat.plans() if with_legacy or not p.legacy]
    page = paginate(plans, query)
    return 200, page.to_dict("plans")


def _plan(run, query, pid):
    cat = run.dataset.catalog
    try:
        return 200, plan_dict(cat.plan(pid), cat.metrics)
    except UnknownPlan:
        return _not_found(f"plan {pid}")


ROUTES = (
    (("customers",), _customers),
    (("customers", None), _customer_one),
    (("customers", None, "invoices"), _customer_invoices),
    (("customers", None, "usage"), _customer_usage),
    (("invoices", None), _invoice),
    (("plans",), _plans),
    (("plans", None), _plan),
)


def handle(path, query, run):
    """Answer ``GET path?query`` from ``run``; returns (status, body dict)."""
    parts = tuple(p for p in str(path).split("/") if p)
    for pattern, fn in ROUTES:
        if len(pattern) != len(parts):
            continue
        if all(want is None or want == got for want, got in zip(pattern, parts)):
            args = [got for want, got in zip(pattern, parts) if want is None]
            try:
                return fn(run, query or {}, *args)
            except BadRequest as e:
                return error(400, "bad_request", str(e))
    return _not_found(f"path {path}")
