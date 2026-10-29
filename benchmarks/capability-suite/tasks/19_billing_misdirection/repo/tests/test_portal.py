"""Customer-portal serializers, pagination and router."""

import json
from decimal import Decimal

import pytest

from meterbill.money import Money
from meterbill.pipeline import run_billing
from meterbill.portal import handle, invoice_dict, paginate, plan_dict, usage_summary_dict
from meterbill.portal.pagination import BadRequest
from meterbill.portal.serializers import decimal_str

from .helpers import DATA, catalog


@pytest.fixture(scope="module")
def run():
    return run_billing(DATA, "2026-03")


def test_decimal_str():
    assert decimal_str(Decimal("1E+3")) == "1000"
    assert decimal_str(Decimal("0.00040")) == "0.0004"
    assert decimal_str(None) is None


def test_paginate_walks_all_items():
    seen, cursor = [], None
    while True:
        q = {"limit": "4"}
        if cursor:
            q["cursor"] = cursor
        page = paginate(range(10), q)
        seen += page.items
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == list(range(10)) and page.total == 10


@pytest.mark.parametrize("q", [{"limit": "0"}, {"limit": "101"}, {"limit": "x"}, {"cursor": "-1"},
                               {"cursor": "50"}, {"limit": "1.5"}])
def test_paginate_bad_values(q):
    with pytest.raises(BadRequest):
        paginate(range(10), q)


def test_defaults_and_exact_fit():
    page = paginate(range(25), {})
    assert page.limit == 25 and page.next_cursor is None and len(page.items) == 25


def test_customers_list_and_get(run):
    status, body = handle("/customers", {"limit": "5"}, run)
    assert status == 200 and len(body["customers"]) == 5 and body["total"] == 14
    assert body["next_cursor"] == "5"
    status, body = handle("/customers/c02/", {}, run)
    assert status == 200 and body["id"] == "C02" and body["currency"] == "EUR" and body["business"] is True


def test_invoice_endpoints(run):
    status, body = handle("/customers/C01/invoices", {}, run)
    assert status == 200 and [i["number"] for i in body["invoices"]] == ["KC-2026-03-C01"]
    status, doc = handle("/invoices/KC-2026-03-C01", {}, run)
    inv = run.invoice("C01")
    assert status == 200 and doc["total"] == f"{inv.total.amount:.2f}"
    assert all(isinstance(ln["amount"], str) for ln in doc["lines"])
    assert doc["lines"][0]["kind"] == "base"
    json.dumps(doc)


def test_amounts_are_strings_everywhere(run):
    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        else:
            assert not isinstance(node, (float, Decimal, Money))
    for inv in run.invoices:
        walk(invoice_dict(inv))


def test_plans(run):
    status, body = handle("/plans", {}, run)
    ids = [p["id"] for p in body["plans"]]
    assert status == 200 and "legacy_basic" not in ids and "team" in ids
    status, body = handle("/plans", {"legacy": "1"}, run)
    assert "legacy_basic" in [p["id"] for p in body["plans"]]
    status, plan = handle("/plans/business", {}, run)
    models = {c["metric"]: c["model"] for c in plan["charges"]}
    assert status == 200 and plan["base_fee"] == "499" and "package" in models.values()
    pkg = [c for c in plan["charges"] if c["model"] == "package"][0]
    assert pkg["package_size"] == "100" and pkg["included"] == "200"


def test_plan_tiers_serialized():
    cat = catalog()
    d = plan_dict(cat.plan("team"), cat.metrics)
    tiers = d["charges"][0]["tiers"]
    assert tiers[-1]["up_to"] is None and tiers[0]["unit_price"] is not None


def test_usage_endpoint(run):
    status, body = handle("/customers/C01/usage", {}, run)
    assert status == 200 and body["period"]["start"] == "2026-03-01"
    names = {m["metric"]: m for m in body["metrics"]}
    assert "api_calls" in names and names["api_calls"]["aggregation"] == "sum"
    direct = usage_summary_dict("C01", run.ingested.records, run.dataset.catalog.metrics)
    assert direct["period"] is None


def test_errors(run):
    assert handle("/customers/NOPE", {}, run)[0] == 404
    assert handle("/customers/NOPE/invoices", {}, run)[0] == 404
    assert handle("/invoices/KC-2026-03-ZZZ", {}, run)[0] == 404
    assert handle("/plans/gold", {}, run)[0] == 404
    status, body = handle("/nothing/here", {}, run)
    assert status == 404 and body["error"] == "not_found"
    status, body = handle("/customers", {"limit": "abc"}, run)
    assert status == 400 and body["error"] == "bad_request"
    assert handle("/customers/C01/invoices", {"cursor": "9"}, run)[0] == 400
