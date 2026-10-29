import pytest

from stockroom.errors import ValidationError
from stockroom.models import Item, Order
from stockroom.money import format_price, parse_price


def test_item_defaults_and_value():
    it = Item("BOLT-001", "Bolt", quantity=4, price_cents=250)
    assert it.value_cents == 1000
    assert it.location == ""
    assert not it.is_low


def test_is_low():
    assert Item("A-001", "x", quantity=2, reorder_level=2).is_low
    assert not Item("A-001", "x", quantity=3, reorder_level=2).is_low
    assert not Item("A-001", "x", quantity=0, reorder_level=0).is_low


def test_with_changes_returns_copy():
    it = Item("A-001", "x")
    it2 = it.with_changes(quantity=5)
    assert it.quantity == 0 and it2.quantity == 5


def test_order_is_open():
    assert Order(1, "A-001", 2).is_open
    assert not Order(1, "A-001", 2, status="fulfilled").is_open


@pytest.mark.parametrize("text,cents", [("12", 1200), ("12.5", 1250), ("$0.07", 7), ("3.10", 310), (4, 400)])
def test_parse_price(text, cents):
    assert parse_price(text) == cents


@pytest.mark.parametrize("bad", ["-1", "1.234", "abc", "", "1,00"])
def test_parse_price_rejects(bad):
    with pytest.raises(ValidationError):
        parse_price(bad)


def test_format_price():
    assert format_price(0) == "0.00"
    assert format_price(1205) == "12.05"
    assert format_price(-5) == "-0.05"
