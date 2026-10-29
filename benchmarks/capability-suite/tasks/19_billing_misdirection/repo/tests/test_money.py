from decimal import Decimal

import pytest

from meterbill import currency
from meterbill.errors import ConfigError, CurrencyMismatch
from meterbill.money import Money, allocate, dec, money_sum, precise, round_to

D = Decimal


def test_dec_accepts_str_int_decimal():
    assert dec("1_000.50") == D("1000.50")
    assert dec(3) == D(3)
    assert dec(D("0.1")) == D("0.1")


@pytest.mark.parametrize("bad", [0.1, True, None, [], "abc", "NaN", "inf"])
def test_dec_rejects(bad):
    with pytest.raises((TypeError, ValueError)):
        dec(bad)


def test_round_to_currency_exponents():
    assert round_to(D("1.005"), "USD") == D("1.01")
    assert round_to(D("1.004999"), "USD") == D("1.00")
    assert round_to(D("1234.5"), "JPY") == D("1235")
    assert round_to(D("1.0005"), "KWD") == D("1.001")
    assert round_to(D("2.675"), "USD", "half_even") == D("2.68")
    assert round_to(D("2.665"), "USD", "half_even") == D("2.66")
    assert round_to(D("9.999"), "USD", "down") == D("9.99")


def test_precise_is_eight_places():
    assert precise(D("1") / D("3")) == D("0.33333333")


def test_money_arithmetic_and_immutability():
    a = Money("10.10", "usd")
    b = Money("0.05", "USD")
    assert a.currency == "USD"
    assert (a + b).amount == D("10.15")
    assert (a - b).amount == D("10.05")
    assert (-a).amount == D("-10.10")
    assert (a * 3).amount == D("30.30")
    assert sum([a, b]) == Money("10.15", "USD")
    with pytest.raises(AttributeError):
        a.amount = D(1)


def test_money_currency_mismatch():
    with pytest.raises(CurrencyMismatch):
        Money(1, "USD") + Money(1, "EUR")


def test_money_rounded_and_minor_units():
    m = Money("12.345", "USD").rounded()
    assert m == Money("12.35", "USD")
    assert m.minor_units() == 1235
    with pytest.raises(ValueError):
        Money("12.345", "USD").minor_units()
    assert Money("1500", "JPY").minor_units() == 1500


def test_money_sum_empty_is_zero():
    assert money_sum([], "EUR") == Money.zero("EUR")


def test_allocate_largest_remainder():
    parts = allocate(Money("10.00", "USD"), [1, 1, 1])
    assert [p.amount for p in parts] == [D("3.34"), D("3.33"), D("3.33")]
    parts = allocate(Money("-0.05", "USD"), [D("2"), D("1")])
    assert [p.amount for p in parts] == [D("-0.03"), D("-0.02")]
    assert sum(allocate(Money("99.99", "USD"), [3, 7, 11, 13]), Money.zero("USD")) == Money("99.99", "USD")


def test_allocate_rejects_bad_weights():
    with pytest.raises(ValueError):
        allocate(Money("1.00", "USD"), [])
    with pytest.raises(ValueError):
        allocate(Money("1.00", "USD"), [0, 0])
    with pytest.raises(ValueError):
        allocate(Money("1.00", "USD"), [1, -1])


def test_currency_registry():
    assert currency.get("jpy").exponent == 0
    assert currency.get("EUR").quantum == D("0.01")
    assert "SEK" in currency.known()
    with pytest.raises(ConfigError):
        currency.get("XXX")
