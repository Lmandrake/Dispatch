from datetime import date
from decimal import Decimal

from ledgerkit.aggregate import aggregate, largest, per_currency
from ledgerkit.models import Posting


def P(account, amount, period="2026-01", tags=(), line=1, cur="USD"):
    a = Decimal(amount)
    return Posting(line=line, on=date(2026, int(period[-2:]), 1), period=period,
                   account=account, description="", amount=a, original_amount=a,
                   original_currency=cur, rate=Decimal(1), tags=tuple(tags))


POSTINGS = [
    P("Expenses:Travel:Air", "100.50", line=1, tags=("trip",)),
    P("Expenses:Travel:Hotel", "200.25", line=2, tags=("trip",)),
    P("Expenses:Travel:Air", "50", "2026-02", line=3),
    P("Expenses:Office", "12.75", "2026-02", line=4, tags=("audit",)),
    P("Income:Consulting", "-400", line=5),
]


def test_leaves():
    t = aggregate(POSTINGS)
    assert t.accounts() == ["Expenses:Office", "Expenses:Travel:Air",
                            "Expenses:Travel:Hotel", "Income:Consulting"]
    assert t.leaf("Expenses:Travel:Air") == Decimal("150.50")
    assert t.leaf("Expenses:Travel:Air", "2026-02") == Decimal("50")
    assert t.periods == ["2026-01", "2026-02"]


def test_rollup_and_grand():
    t = aggregate(POSTINGS)
    assert t.balance("Expenses:Travel") == Decimal("350.75")
    assert t.balance("Expenses", "2026-02") == Decimal("62.75")
    assert t.grand("2026-01") == Decimal("-99.25")
    assert t.grand() == Decimal("-36.5")
    assert t.top_level() == ["Expenses", "Income"]
    assert t.by_period("Income") == {"2026-01": Decimal("-400"), "2026-02": Decimal(0)}


def test_filters():
    assert aggregate(POSTINGS, tags=["TRIP"]).grand() == Decimal("300.75")
    assert aggregate(POSTINGS, exclude_tags=["audit"]).balance("Expenses") == Decimal("350.75")
    assert aggregate(POSTINGS, accounts=["Expenses:Travel"]).accounts() == [
        "Expenses:Travel:Air", "Expenses:Travel:Hotel"]
    assert aggregate(POSTINGS, depth=1).accounts() == ["Expenses", "Income"]


def test_per_currency_and_largest():
    assert per_currency(POSTINGS) == {"USD": Decimal("-36.5")}
    assert [p.line for p in largest(POSTINGS, 2)] == [5, 2]
