from decimal import Decimal

from shop import calc_total
from shop.cart import Cart
from shop.invoice import render_invoice
from shop.registry import run
from shop.report import daily_report

LINES = [(10, 2), ("2.50", 4)]


def test_calc_total():
    assert calc_total(LINES) == Decimal("32.40")
    assert calc_total(LINES, discount_pct=50, taxed=False) == Decimal("15.00")


def test_cart():
    assert Cart().add(10, 2).add("2.50", 4).total() == Decimal("32.40")


def test_invoice():
    assert render_invoice("ann", LINES).endswith("TOTAL 32.40")


def test_registry():
    assert run("total", LINES, taxed=False) == Decimal("30.00")


def test_report():
    assert daily_report([("a", LINES), ("a", [(1, 1)])]) == {"a": Decimal("31.00")}
