from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import AccountError, LedgerError, ParseError
from ledgerkit.parser import parse_ledger

BASIC = """\
!account Expenses:Travel:Air
!alias air Expenses:Travel:Air
2026-01-09 | air | SFO-BOS | 412.37 | | trip, Trip ,x
!locale de_DE
!currency EUR
!tag berlin
05.03.2026 | air | Rückflug | 1.214,60
!endtag berlin
2026-03-06 | Expenses:Travel:Air | Extra | -3,5 | GBP
"""


def test_basic_entries():
    led = parse_ledger(BASIC)
    a, b, c = led.entries
    assert (a.on, a.account, a.amount, a.currency, a.tags) == (
        date(2026, 1, 9), "Expenses:Travel:Air", Decimal("412.37"), "USD", ("trip", "x"))
    assert (b.on, b.amount, b.currency, b.tags) == (
        date(2026, 3, 5), Decimal("1214.60"), "EUR", ("berlin",))
    assert (c.amount, c.currency, c.tags) == (Decimal("-3.5"), "GBP", ())
    assert led.currencies() == ["EUR", "GBP", "USD"]


def test_split_directive():
    led = parse_ledger("!split rent Expenses:Rent:HQ=3 Expenses:Rent:Lab=1\n"
                       "2026-01-15 | @Rent | Jan | 100\n")
    assert led.splits["rent"].shares == (("Expenses:Rent:HQ", Decimal(3)),
                                         ("Expenses:Rent:Lab", Decimal(1)))
    assert led.entries[0].account == "@rent"


@pytest.mark.parametrize("text", [
    "2026-01-01 | Expenses:A | x\n",
    "2026-13-01 | Expenses:A | x | 1\n",
    "2026-01-01 | Expenses:A | x | 1 | EURO\n",
    "!bogus 1\n",
    "!endtag foo\n",
    "2026-01-01 | @nope | x | 1\n",
    "!split s Expenses:A=0\n",
])
def test_parse_errors(text):
    with pytest.raises(LedgerError):
        parse_ledger(text)


def test_strict_directive():
    with pytest.raises(AccountError):
        parse_ledger("!account Expenses:A\n!strict\n2026-01-01 | Expenses:B | x | 1\n")


def test_error_carries_line_number():
    with pytest.raises(ParseError) as info:
        parse_ledger("; c\n2026-01-01 | Expenses:A | x | 1\n2026-01-02 | Expenses:A | y | 1.2.3\n",
                     source="f.ledger")
    assert info.value.line == 3
    assert str(info.value).startswith("f.ledger:3:")
