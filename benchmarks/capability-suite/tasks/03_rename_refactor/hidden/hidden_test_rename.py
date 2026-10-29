import pathlib
from decimal import Decimal

import shop
import shop.pricing
from shop.cart import Cart
from shop.invoice import render_invoice
from shop.registry import run, resolve, OPERATIONS
from shop.report import daily_report

ROOT = pathlib.Path(__file__).parent
LINES = [(10, 2), ("2.50", 4)]


def test_old_name_gone_from_source():
    offenders = []
    for p in ROOT.rglob("*.py"):
        if p.name.startswith("hidden_") or any(part.startswith(".") for part in p.parts):
            continue
        if "calc_total" in p.read_text():
            offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []


def test_old_name_not_an_attribute():
    assert not hasattr(shop.pricing, "calc_total")
    assert not hasattr(shop, "calc_total")


def test_new_name():
    from shop import compute_order_total
    assert compute_order_total is shop.pricing.compute_order_total
    assert compute_order_total(LINES) == Decimal("32.40")
    assert compute_order_total(LINES, discount_pct=50, taxed=False) == Decimal("15.00")


def test_callers_still_work():
    assert Cart().add(10, 2).add("2.50", 4).total(discount_pct=10) == Decimal("29.16")
    assert render_invoice("ann", LINES).endswith("TOTAL 32.40")
    assert daily_report([("a", LINES), ("a", [(1, 1)])]) == {"a": Decimal("31.00")}


def test_registry():
    assert set(OPERATIONS) == {"subtotal", "total", "invoice"}
    assert resolve("total") is shop.pricing.compute_order_total
    assert run("total", LINES, taxed=False) == Decimal("30.00")
    assert run("subtotal", LINES) == Decimal("30.00")
    assert "TOTAL" in run("invoice", "bob", LINES)
