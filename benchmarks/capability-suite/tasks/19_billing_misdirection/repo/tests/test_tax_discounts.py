from datetime import date
from decimal import Decimal

import pytest

from meterbill.credits import apply_credits, parse_credits, usable_grants
from meterbill.discounts import active_coupons, apply_coupons, parse_coupons, parse_redemptions
from meterbill.errors import ConfigError, TaxError
from meterbill.money import Money
from meterbill.tax import TaxTable, parse_tax

from .helpers import DATA, converter, customer

D = Decimal
USD = lambda a: Money(a, "USD")  # noqa: E731


def table():
    return TaxTable(parse_tax((DATA / "tax.toml").read_text()))


def test_tax_per_invoice_half_up():
    r = table().compute(customer(jurisdiction="US-NY"), [USD("100.00"), USD("13.37")], USD("0"))
    assert r.taxable == USD("113.37") and r.tax == USD("10.06")
    assert r.rule.percent() == "8.875%"


def test_tax_per_line_sums_rounded_line_taxes():
    r = table().compute(customer(jurisdiction="US-TX"), [USD("0.08"), USD("0.08"), USD("0.08")], USD("0"))
    assert r.tax == USD("0.03")
    r2 = table().compute(customer(jurisdiction="US-CO"), [USD("0.08"), USD("0.08"), USD("0.08")], USD("0"))
    assert r2.tax == USD("0.01")


def test_tax_modes():
    t = table()
    assert t.compute(customer(jurisdiction="JP", currency="JPY"), [Money("999", "JPY")], Money("0", "JPY")).tax == Money("99", "JPY")
    assert t.compute(customer(jurisdiction="CH", currency="CHF"), [Money("50.00", "CHF")], Money("0", "CHF")).tax == Money("4.05", "CHF")


def test_reverse_charge_needs_tax_id():
    t = table()
    eur = lambda a: Money(a, "EUR")  # noqa: E731
    rc = t.compute(customer(jurisdiction="DE", currency="EUR", tax_id="DE123"), [eur("100.00")], eur("0"))
    assert rc.reverse_charged and rc.tax == eur("0") and rc.note
    b2c = t.compute(customer(jurisdiction="DE", currency="EUR"), [eur("100.00")], eur("0"))
    assert not b2c.reverse_charged and b2c.tax == eur("19.00")


def test_tax_unknown_jurisdiction():
    with pytest.raises(TaxError):
        table().compute(customer(jurisdiction="XX"), [USD("1.00")], USD("0"))


def test_coupon_parsing_rules():
    coupons = parse_coupons((DATA / "coupons.toml").read_text())
    assert coupons["WELCOME10"].is_percent and coupons["WELCOME10"].cycles == 3
    assert coupons["PARTNER50"].currency == "USD"
    with pytest.raises(ConfigError):
        parse_coupons('[coupons.X]\npercent_off = "10"\namount_off = "5"\n')
    with pytest.raises(ConfigError):
        parse_coupons('[coupons.X]\namount_off = "5"\ncurrency = "USD"\napplies_to = "usage"\n')


def test_coupon_activity_windows():
    coupons = parse_coupons((DATA / "coupons.toml").read_text())
    reds = parse_redemptions("customer,coupon,first_cycle\nC1,WELCOME10,2026-01\nC1,PARTNER50,2026-02\n", coupons=coupons)
    assert [c.code for c in active_coupons(coupons, reds, "C1", "2026-01")] == ["WELCOME10"]
    assert [c.code for c in active_coupons(coupons, reds, "C1", "2026-03")] == ["WELCOME10", "PARTNER50"]
    assert [c.code for c in active_coupons(coupons, reds, "C1", "2026-04")] == ["PARTNER50"]
    assert active_coupons(coupons, reds, "C1", "2025-12") == []


def test_apply_coupons_percent_then_fixed_capped():
    coupons = parse_coupons((DATA / "coupons.toml").read_text())
    lines = [("base", USD("49.00")), ("usage", USD("10.01"))]
    out = apply_coupons([coupons["SPRING15"], coupons["PARTNER50"]], lines, USD("59.01"), converter(), date(2026, 3, 31))
    assert [a.amount for a in out] == [USD("1.50"), USD("50.00")]
    out = apply_coupons([coupons["WELCOME10"], coupons["PARTNER50"]], [("base", USD("40.00"))], USD("40.00"),
                        converter(), date(2026, 3, 31))
    assert [a.amount for a in out] == [USD("4.00"), USD("36.00")]


def test_credits_order_and_remaining():
    grants = parse_credits("customer,grant_id,currency,amount,granted,expires\n"
                           "C1,G2,USD,100.00,2026-01-01,\n"
                           "C1,G1,USD,30.00,2026-01-01,2026-06-01\n"
                           "C1,G0,USD,30.00,2026-01-01,2026-02-01\n")
    usable = usable_grants(grants, "C1", date(2026, 4, 1))
    assert [g.grant_id for g in usable] == ["G1", "G2"]
    uses, due = apply_credits(usable, USD("75.50"), converter(), date(2026, 3, 31))
    assert [u.applied for u in uses] == [USD("30.00"), USD("45.50")]
    assert [u.remaining for u in uses] == [USD("0"), USD("54.50")]
    assert due == USD("0")
