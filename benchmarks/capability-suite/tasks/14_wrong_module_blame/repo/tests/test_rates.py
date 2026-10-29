from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import ParseError, RateNotFound
from ledgerkit.rates import load_rates

TEXT = """\
base USD
2026-02-01 EUR 1.0790
2026-01-01 EUR 1.0850   ; first
2026-03-16 EUR 1.0817
"""


def test_rate_in_effect_from_its_day():
    t = load_rates(TEXT)
    assert t.base == "USD"
    assert t.rate_on("EUR", date(2026, 1, 31)).value == Decimal("1.0850")
    assert t.rate_on("EUR", date(2026, 2, 1)).value == Decimal("1.0790")
    assert t.rate_on("EUR", date(2026, 3, 15)).value == Decimal("1.0790")
    assert t.rate_on("EUR", date(2026, 3, 16)).value == Decimal("1.0817")
    assert t.rate_on("usd", date(1999, 1, 1)).value == 1


def test_missing_rates():
    t = load_rates(TEXT)
    with pytest.raises(RateNotFound):
        t.rate_on("EUR", date(2025, 12, 31))
    with pytest.raises(RateNotFound):
        t.rate_on("CHF", date(2026, 1, 1))


@pytest.mark.parametrize("bad", [
    "2026-01-01 EUR\n", "2026-01-01 EUR 0\n", "2026-01-01 USD 1\n",
    "2026-01-01 EUR 1\n2026-01-01 EUR 2\n", "base USD\nbase EUR\n", "2026-02-30 EUR 1\n",
])
def test_bad_rates(bad):
    with pytest.raises(ParseError):
        load_rates(bad)
