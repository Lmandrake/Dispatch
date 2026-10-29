from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import AllocationError, RateNotFound
from ledgerkit.normalize import Normalizer, allocate, normalize
from ledgerkit.parser import parse_ledger
from ledgerkit.rates import load_rates

RATES = load_rates("2026-01-01 EUR 1.0850\n2026-02-01 EUR 1.0790\n2026-01-01 JPY 0.00671\n")


def test_convert_quantizes_to_micro():
    n = Normalizer(RATES)
    amount, rate = n.convert_amount(Decimal("12.345"), "EUR", date(2026, 1, 3))
    assert rate == Decimal("1.0850")
    assert amount == Decimal("13.394325")
    amount, _ = n.convert_amount(Decimal("12000"), "JPY", date(2026, 2, 27))
    assert amount == Decimal("80.520000")


def test_base_currency_unchanged():
    n = Normalizer(RATES)
    assert n.convert_amount(Decimal("84.225"), "USD", date(2026, 1, 1))[0] == Decimal("84.225")


def test_rate_lookups_are_memoised():
    n = Normalizer(RATES)
    for _ in range(50):
        n.convert_amount(Decimal("1"), "EUR", date(2026, 1, 10))
    assert n.lookups == 1


def test_missing_rate_reports_line():
    led = parse_ledger("2026-01-01 | Expenses:A | x | 1 | CHF\n")
    with pytest.raises(RateNotFound) as info:
        normalize(led, RATES)
    assert info.value.line == 1


def test_allocate_sums_exactly():
    parts = allocate(Decimal("100"), [("a", Decimal(1)), ("b", Decimal(1)), ("c", Decimal(1))])
    assert [p for _, p in parts] == [Decimal("33.333334"), Decimal("33.333333"),
                                     Decimal("33.333333")]
    assert sum(p for _, p in parts) == Decimal("100")
    neg = allocate(Decimal("-10"), [("a", Decimal(2)), ("b", Decimal(1)), ("z", Decimal(0))])
    assert neg == [("a", Decimal("-6.666667")), ("b", Decimal("-3.333333")), ("z", Decimal(0))]


def test_allocate_errors():
    with pytest.raises(AllocationError):
        allocate(Decimal(1), [])
    with pytest.raises(AllocationError):
        allocate(Decimal(1), [("a", Decimal(0))])


def test_split_entry_expands():
    led = parse_ledger("!split rent Expenses:Rent:HQ=3 Expenses:Rent:Lab=1\n"
                       "2026-02-15 | @rent | Feb | 1000 | EUR\n")
    ps = normalize(led, RATES)
    assert [(p.account, p.amount, p.original_amount) for p in ps] == [
        ("Expenses:Rent:HQ", Decimal("809.250000"), Decimal("750.000000")),
        ("Expenses:Rent:Lab", Decimal("269.750000"), Decimal("250.000000")),
    ]
    assert {p.period for p in ps} == {"2026-02"}
