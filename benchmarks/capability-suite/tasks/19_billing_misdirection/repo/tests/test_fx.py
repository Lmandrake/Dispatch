from datetime import date
from decimal import Decimal

import pytest

from meterbill.errors import ConfigError, RateNotFound
from meterbill.fx import Converter, parse_rates
from meterbill.money import Money

from .helpers import converter

D = Decimal
RATES = ("effective,currency,per_usd\n"
         "2026-03-01,EUR,0.9210\n2026-03-16,EUR,0.9234\n2026-03-01,GBP,0.7915\n2026-03-01,JPY,149.85\n")


def test_per_usd_effective_ranges():
    t = parse_rates(RATES)
    assert t.per_usd("EUR", date(2026, 3, 1)) == D("0.9210")
    assert t.per_usd("EUR", date(2026, 3, 15)) == D("0.9210")
    assert t.per_usd("EUR", date(2026, 3, 16)) == D("0.9234")
    assert t.per_usd("USD", date(1999, 1, 1)) == 1
    with pytest.raises(RateNotFound):
        t.per_usd("EUR", date(2026, 2, 28))
    with pytest.raises(RateNotFound):
        t.per_usd("CHF", date(2026, 3, 5))


def test_cross_rate_and_convert():
    c = Converter(parse_rates(RATES))
    assert c.cross_rate("USD", "EUR", date(2026, 3, 20)) == D("0.9234000000")
    assert c.cross_rate("EUR", "GBP", date(2026, 3, 5)) == D("0.8593919653")
    m = c.convert(Money("100.00", "USD"), "JPY", date(2026, 3, 5))
    assert m == Money("14985.00000000", "JPY")
    assert c.convert(Money("5", "EUR"), "EUR", date(2026, 3, 5)) == Money("5", "EUR")


def test_rate_file_errors():
    with pytest.raises(ConfigError):
        parse_rates("effective,currency,per_usd\n2026-03-01,EUR,0\n")
    with pytest.raises(ConfigError):
        parse_rates("effective,currency,per_usd\n2026-03-01,EUR,1\n2026-03-01,EUR,2\n")
    with pytest.raises(ConfigError):
        parse_rates("effective,currency,per_usd\n2026-03-01,USD,1\n")
    with pytest.raises(ConfigError):
        parse_rates("effective,currency\n")


def test_dataset_rates_load():
    c = converter()
    assert c.table.currencies() == ["AUD", "CHF", "EUR", "GBP", "JPY", "SEK"]
