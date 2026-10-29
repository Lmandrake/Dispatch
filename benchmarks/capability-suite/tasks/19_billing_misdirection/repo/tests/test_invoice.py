"""Invoice assembly on small hand-built inputs."""

from datetime import date
from decimal import Decimal

from meterbill.discounts import Redemption, parse_coupons
from meterbill.credits import parse_credits
from meterbill.invoice import BillingContext, build_invoice, invoice_check
from meterbill.money import Money
from meterbill.subscriptions import parse_subscriptions
from meterbill.tax import TaxTable, parse_tax

from .helpers import DATA, catalog, converter, customer, rec

D = Decimal
USD = lambda a: Money(a, "USD")  # noqa: E731


def ctx(subs, **kw):
    cat = catalog()
    return BillingContext(
        catalog=cat,
        subscriptions=parse_subscriptions("customer,plan,effective\n" + subs, catalog=cat),
        tax=TaxTable(parse_tax((DATA / "tax.toml").read_text())),
        converter=converter(), **kw)


def test_simple_starter_invoice():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    records = [rec("T01", "api_calls", 150000, "2026-02-10T12:00:00Z"),
               rec("T01", "storage_gb", "70", "2026-02-27T12:00:00Z")]
    inv = build_invoice(ctx("T01,starter,2025-01-01\n"), c, "2026-02", records)
    assert inv.number == "KC-2026-02-T01"
    assert [ln.amount for ln in inv.lines] == [USD("49.00"), USD("25.00"), USD("0.46")]
    assert inv.subtotal == USD("74.46") and inv.tax.tax == USD("0") and inv.total == USD("74.46")
    assert inv.issued == date(2026, 3, 1) and inv.due == date(2026, 3, 31)
    assert invoice_check(inv) == []


def test_usage_outside_period_not_billed():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    records = [rec("T01", "api_calls", 500000, "2026-03-01T00:00:00Z"),
               rec("T01", "api_calls", 500000, "2026-01-31T23:59:59Z")]
    inv = build_invoice(ctx("T01,starter,2025-01-01\n"), c, "2026-02", records)
    assert inv.lines[1].quantity == 0
    assert inv.usage_counts == {"billed": 0, "unbilled": 0, "outside": 2}


def test_unbilled_before_subscription():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    records = [rec("T01", "api_calls", 1000, "2026-02-03T10:00:00Z"),
               rec("T01", "api_calls", 1000, "2026-02-20T10:00:00Z")]
    inv = build_invoice(ctx("T01,starter,2026-02-15\n"), c, "2026-02", records)
    assert inv.usage_counts["unbilled"] == 1
    assert any("not billed" in n for n in inv.notes)


def test_percent_coupon_on_usage_only():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    coupons = parse_coupons((DATA / "coupons.toml").read_text())
    records = [rec("T01", "api_calls", 300000, "2026-02-10T12:00:00Z")]
    inv = build_invoice(ctx("T01,starter,2025-01-01\n", coupons=coupons,
                            redemptions=[Redemption("T01", "SPRING15", "2026-02")]), c, "2026-02", records)
    assert inv.discount_total == USD("15.00")
    assert inv.total == USD("134.00")


def test_credit_reduces_amount_due_not_total():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    grants = parse_credits("customer,grant_id,currency,amount,granted,expires\nT01,G1,USD,20.00,2026-01-01,\n")
    inv = build_invoice(ctx("T01,starter,2025-01-01\n", grants=grants), c, "2026-02", [])
    assert inv.total == USD("49.00")
    assert inv.credit_total == USD("20.00") and inv.amount_due == USD("29.00")
    assert invoice_check(inv) == []


def test_reverse_charge_note():
    c = customer(id="T01", timezone="Europe/Berlin", currency="EUR", jurisdiction="DE", tax_id="DE999")
    inv = build_invoice(ctx("T01,team_eu,2025-01-01\n"), c, "2026-02", [])
    assert inv.tax.reverse_charged and inv.notes[0].startswith("Reverse charge")
    assert inv.total == Money("185.00", "EUR")


def test_plan_currency_converted_before_rounding():
    c = customer(id="T01", timezone="UTC", currency="JPY", jurisdiction="US-CA")
    inv = build_invoice(ctx("T01,starter,2025-01-01\n"), c, "2026-02", [])
    # 49 USD at the 2026-02-01 quote of 151.20 JPY/USD = 7408.8, rounded once
    assert inv.lines[0].amount == Money("7409", "JPY")
