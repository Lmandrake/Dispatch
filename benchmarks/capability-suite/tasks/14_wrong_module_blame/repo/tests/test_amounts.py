from decimal import Decimal

import pytest

from ledgerkit.amounts import parse_amount, parse_c_decimal
from ledgerkit.errors import AmountError


@pytest.mark.parametrize("text,locale,want", [
    ("1234.56", "en_US", "1234.56"),
    ("1,234.56", "en_US", "1234.56"),
    ("-1,234.56", "en_US", "-1234.56"),
    ("(1,234.56)", "en_US", "-1234.56"),
    ("1,234.56-", "en_US", "-1234.56"),
    ("+12", "en_US", "12"),
    (".5", "en_US", "0.5"),
    ("84.225", "en_US", "84.225"),
    ("1.046,40", "de_DE", "1046.40"),
    ("-0,5", "de_DE", "-0.5"),
    ("1'234.5", "de_CH", "1234.5"),
    ("1 234,50", "fr_FR", "1234.50"),
    ("12,000", "en_US", "12000"),
    ("1,234,567.891", "en_US", "1234567.891"),
])
def test_parse_ok(text, locale, want):
    got = parse_amount(text, locale)
    assert got == Decimal(want)
    assert isinstance(got, Decimal)


def test_fraction_digits_are_kept_exactly():
    assert parse_amount("0.0000001").as_tuple().exponent == -7


@pytest.mark.parametrize("text,locale", [
    ("", "en_US"), ("-", "en_US"), ("1,23.4", "en_US"), ("1.234,5", "en_US"),
    ("1.23,4", "de_DE"), ("--1", "en_US"), ("(1)-", "en_US"), ("1.2.3", "en_US"),
    ("1,2345", "en_US"), ("abc", "en_US"), ("1 234", "en_US"),
])
def test_parse_bad(text, locale):
    with pytest.raises(AmountError):
        parse_amount(text, locale)


def test_c_decimal():
    assert parse_c_decimal(" 1.0850 ") == Decimal("1.0850")
    with pytest.raises(AmountError):
        parse_c_decimal("1,08")
    with pytest.raises(AmountError):
        parse_c_decimal("inf")
