from decimal import Decimal
from pathlib import Path

import pytest

from ledgerkit.aggregate import aggregate
from ledgerkit.pipeline import read_text, run
from ledgerkit.report import build_report, format_money, render_text, summary_line

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GOLDEN = Path(__file__).resolve().parent / "golden"


def q1(**kw):
    return run(read_text(DATA / "q1.ledger"), read_text(DATA / "rates.txt"), **kw)


@pytest.mark.parametrize("value,want", [
    ("0", "0.00"),
    ("1.005", "1.01"),
    ("2.675", "2.68"),
    ("-2.675", "-2.68"),
    ("1.0049999", "1.00"),
    ("-0.004", "0.00"),
    ("1234567.891", "1,234,567.89"),
    ("999.995", "1,000.00"),
])
def test_format_money_half_up(value, want):
    assert format_money(Decimal(value)) == want


def test_format_money_options():
    assert format_money(Decimal("-1234.5"), parens=True) == "(1,234.50)"
    assert format_money(Decimal("3"), plus=True) == "+3.00"
    assert format_money(Decimal("1234.5"), locale="de_DE") == "1.234,50"
    assert format_money(Decimal("1234.5"), locale="fr_FR") == "1\u202f234,50"
    assert format_money(Decimal("1234.5"), 0) == "1,235"
    assert format_money(Decimal("1.2345"), 3) == "1.235"


def test_columns_are_right_aligned():
    lines = q1().splitlines()
    header, rule = lines[1], lines[2]
    assert len(rule) == len(header)
    body = [l for l in lines[3:] if not l.startswith("=")]
    for line in body:
        assert len(line) == len(header), line


def test_zero_cells_show_dash():
    workshops = [l for l in q1().splitlines() if l.strip().startswith("Workshops")][0]
    assert workshops.split()[2:4] == ["-", "-"]


def test_report_title_and_notes():
    from ledgerkit.models import Posting
    from datetime import date
    p = Posting(line=1, on=date(2026, 1, 1), period="2026-01", account="Expenses:A",
                description="", amount=Decimal("1.5"), original_amount=Decimal("1.5"),
                original_currency="USD", rate=Decimal(1))
    rep = build_report(aggregate([p]), title="T", notes=["unaudited"])
    text = render_text(rep)
    assert text.startswith("T\n")
    assert text.endswith("* unaudited\n")
    assert summary_line(rep) == "TOTAL USD 1.50 over 1 period"


def test_totals_rounding():
    """The monthly Q1 report must match the figures the accountants signed off."""
    assert q1() == (GOLDEN / "q1_month.txt").read_text()


def test_quarter_csv_totals_match_cells():
    """With a single period, every row's total must equal its only cell."""
    text = q1(period="quarter", fmt="csv")
    for line in text.splitlines()[1:]:
        account, cell, total = line.split(",")
        assert cell == total, account
    assert text == (GOLDEN / "q1_quarter.csv").read_text()
