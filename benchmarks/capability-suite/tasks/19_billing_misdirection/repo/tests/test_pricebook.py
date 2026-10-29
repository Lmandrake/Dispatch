"""Price book rendering."""

from meterbill.catalog import parse_catalog
import csv
import io

from meterbill.pricebook import (allowance_text, price_book_csv, price_book_rows, render_price_book,
                                 tier_lines)

from .helpers import catalog

CAT = """
[metrics.calls]
name = "Calls"
unit = "calls"
[metrics.seats]
name = "Seats"
unit = "seats"
aggregation = "max"

[plans.p]
name = "P"
currency = "USD"
base_fee = "10"

[[plans.p.charges]]
metric = "calls"
model = "graduated"
included = 500
tiers = [{ up_to = 1000000, unit_price = "0.0004" }, { up_to = 5000000, unit_price = "0.0003", flat_fee = "5.00" }, { up_to = "inf", unit_price = "0.0002" }]

[[plans.p.charges]]
metric = "seats"
model = "flat"
unit_price = "7"

[plans.q]
name = "Q"
currency = "EUR"
base_fee = "0"
legacy = true
"""


def test_graduated_tiers_read_like_prose():
    cat = parse_catalog(CAT)
    ch = cat.plan("p").charges[0]
    lines = tier_lines(ch, cat.metrics.get("calls"), "USD")
    assert lines == ["first 1,000,000 calls at 0.0004 USD",
                     "next 4,000,000 calls at 0.0003 USD + 5.00 USD flat",
                     "above 5,000,000 calls at 0.0002 USD"]
    assert allowance_text(ch, cat.metrics.get("calls")) == "500 calls included"


def test_other_models():
    cat = catalog()
    biz = cat.plan("business")
    metrics = cat.metrics
    api = tier_lines(biz.charge_for("api_calls"), metrics.get("api_calls"), "USD")
    assert api[0] == "1-1,000,000 calls: all at 0.00035 USD" and api[-1].startswith("above 5,000,000 calls")
    pkg = tier_lines(biz.charge_for("storage_gb"), metrics.get("storage_gb"), "USD")
    assert pkg == ["1.90 USD per block of 100 GB (partial blocks charged in full)"]
    per_unit = tier_lines(cat.plan("starter").charge_for("api_calls"), metrics.get("api_calls"), "USD")
    assert per_unit == ["0.0005 USD per call"]


def test_render_has_every_plan_and_legacy_flag():
    cat = catalog()
    text = render_price_book(cat)
    for plan in cat.plans():
        assert f"[{plan.id}]" in text
    assert "legacy: existing subscribers only" in text
    assert "[legacy_basic]" not in render_price_book(cat, include_legacy=False)
    assert all(len(ln) <= 72 for ln in text.splitlines())
    assert render_price_book(cat) == text


def test_render_flat_and_no_charges():
    text = render_price_book(parse_catalog(CAT))
    assert "7.00 USD once, whatever the quantity" in text
    assert "No metered charges." in text
    assert "Seats (billed by peak in the period)" in text


def test_csv_rows_and_round_trip():
    cat = parse_catalog(CAT)
    text = price_book_csv(cat)
    rows = list(csv.DictReader(io.StringIO(text)))
    calls = [r for r in rows if r["metric"] == "calls"]
    assert [r["tier"] for r in calls] == ["1", "2", "3"]
    assert [r["up_to"] for r in calls] == ["1000000", "5000000", ""]
    assert calls[1]["flat_fee"] == "5" and calls[0]["included"] == "500"
    assert [r["unit_price"] for r in calls] == ["0.0004", "0.0003", "0.0002"]
    flat = [r for r in rows if r["metric"] == "seats"][0]
    assert flat["model"] == "flat" and flat["unit_price"] == "7"


def test_csv_plan_without_charges_and_legacy_filter():
    cat = parse_catalog(CAT)
    rows = price_book_rows(cat)
    q = [r for r in rows if r[0] == "q"]
    assert len(q) == 1 and q[0][3] == "yes" and q[0][5] == ""
    assert not [r for r in price_book_rows(cat, include_legacy=False) if r[0] == "q"]


def test_no_float_artifacts_for_sample_catalogue():
    text = price_book_csv(catalog())
    assert "e-" not in text.lower() and "E-" not in text
