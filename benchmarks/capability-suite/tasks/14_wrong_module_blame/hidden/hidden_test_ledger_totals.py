"""Hidden tests for 14_wrong_module_blame (files sit at the workdir root)."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ledgerkit.aggregate import Totals, aggregate, rollup
from ledgerkit.models import Posting, Report, ReportRow
from ledgerkit.money import round_money
from ledgerkit.normalize import Normalizer, normalize
from ledgerkit.parser import parse_ledger
from ledgerkit.pipeline import load, run
from ledgerkit.rates import load_rates
from ledgerkit.report import build_report, format_money, render_csv, render_text

HERE = Path(__file__).resolve().parent
LEDGER = (HERE / "data" / "q1.ledger").read_text()
RATES_TEXT = (HERE / "data" / "rates.txt").read_text()

GOLDEN_MONTH = 'Ledger by month\nUSD             2026-01    2026-02    2026-03       Total\n---------------------------------------------------------\nExpenses       3,707.00   3,453.57   4,104.99   11,265.56\n  Office         199.00     118.36      95.31      412.66\n    Software     199.00      80.52      50.00      329.52\n    Supplies          -      37.84      45.31       83.15\n  Rent         2,400.00   2,400.00   2,400.00    7,200.00\n    HQ         1,800.00   1,800.00   1,800.00    5,400.00\n    Lab          600.00     600.00     600.00    1,800.00\n  Travel       1,108.00     935.21   1,609.68    3,652.89\n    Air          412.37     490.95     232.09    1,135.41\n    Hotel        611.40     366.85   1,288.80    2,267.05\n    Meals         84.23      77.42      88.80      250.44\nIncome        -5,350.00  -3,975.50  -5,210.75  -14,536.25\n  Consulting  -4,200.00  -3,975.50  -5,210.75  -13,386.25\n  Workshops   -1,150.00          -          -   -1,150.00\n=========================================================\nTOTAL         -1,643.01    -521.93  -1,105.76   -3,270.69\n'

GOLDEN_QUARTER_CSV = 'account,2026-Q1,total\nExpenses,11265.56,11265.56\nExpenses:Office,412.66,412.66\nExpenses:Office:Software,329.52,329.52\nExpenses:Office:Supplies,83.15,83.15\nExpenses:Rent,7200.00,7200.00\nExpenses:Rent:HQ,5400.00,5400.00\nExpenses:Rent:Lab,1800.00,1800.00\nExpenses:Travel,3652.89,3652.89\nExpenses:Travel:Air,1135.41,1135.41\nExpenses:Travel:Hotel,2267.05,2267.05\nExpenses:Travel:Meals,250.44,250.44\nIncome,-14536.25,-14536.25\nIncome:Consulting,-13386.25,-13386.25\nIncome:Workshops,-1150.00,-1150.00\nTOTAL,-3270.69,-3270.69\n'

D = Decimal


def q1(**kw):
    return run(LEDGER, RATES_TEXT, **kw)


# ---- the visible symptom ---------------------------------------------------

def test_month_report_matches_signed_off_figures():
    assert q1() == GOLDEN_MONTH


def test_quarter_csv_matches_signed_off_figures():
    text = q1(period="quarter", fmt="csv")
    assert text == GOLDEN_QUARTER_CSV
    for line in text.splitlines()[1:]:
        account, cell, total = line.split(",")
        assert cell == total, account


def test_summary_line():
    assert q1(fmt="summary") == "TOTAL USD -3,270.69 over 3 periods\n"


# ---- root cause 1: rate memo keyed on the period ----------------------------

EUR = load_rates("2026-01-01 EUR 1.0850\n2026-02-01 EUR 1.0790\n2026-03-01 EUR 1.0815\n"
                 "2026-03-16 EUR 1.0817\n2026-01-01 GBP 1.2700\n2026-01-20 GBP 1.2500\n")


def test_mid_month_rate_change_after_earlier_lookup():
    n = Normalizer(EUR)
    a, r1 = n.convert_amount(D("100"), "EUR", date(2026, 3, 4))
    b, r2 = n.convert_amount(D("100"), "EUR", date(2026, 3, 17))
    assert (r1, r2) == (D("1.0815"), D("1.0817"))
    assert (a, b) == (D("108.150000"), D("108.170000"))


def test_mid_month_rate_change_lookup_order_reversed():
    n = Normalizer(EUR)
    assert n.rate_for("EUR", date(2026, 3, 31)) == D("1.0817")
    assert n.rate_for("EUR", date(2026, 3, 1)) == D("1.0815")
    assert n.rate_for("EUR", date(2026, 3, 15)) == D("1.0815")
    assert n.rate_for("EUR", date(2026, 3, 16)) == D("1.0817")


@pytest.mark.parametrize("period", ["month", "quarter", "year"])
def test_rate_follows_effective_day_for_every_period_kind(period):
    led = parse_ledger(
        "2026-01-10 | Expenses:A | a | 100 | GBP\n"
        "2026-01-25 | Expenses:A | b | 100 | GBP\n"
        "2026-01-31 | Expenses:A | c | 10 | EUR\n"
        "2026-02-01 | Expenses:A | d | 10 | EUR\n"
        "2026-03-20 | Expenses:A | e | 10 | EUR\n")
    ps = normalize(led, EUR, period=period)
    assert [p.rate for p in ps] == [D("1.2700"), D("1.2500"), D("1.0850"), D("1.0790"),
                                    D("1.0817")]
    assert [p.amount for p in ps] == [D("127.000000"), D("125.000000"), D("10.850000"),
                                      D("10.790000"), D("10.817000")]


def test_q1_postings_use_the_march_16_rate():
    book = load(LEDGER, RATES_TEXT)
    by_line = {p.line: p for p in book.postings}
    assert by_line[38].rate == D("1.0815")
    assert by_line[43].rate == D("1.0817")
    assert by_line[44].rate == D("1.0817")
    assert by_line[43].amount == D("157.116925")
    assert by_line[44].amount == D("25.690375")


def test_split_entry_uses_its_own_day_rate():
    led = parse_ledger("!split s Expenses:X=1 Expenses:Y=1\n"
                       "2026-03-02 | Expenses:Z | z | 1 | EUR\n"
                       "2026-03-20 | @s | split | 100 | EUR\n")
    ps = normalize(led, EUR)
    assert [(p.account, p.amount) for p in ps[1:]] == [
        ("Expenses:X", D("54.085000")), ("Expenses:Y", D("54.085000"))]


def test_rate_lookups_still_memoised():
    n = Normalizer(EUR)
    for _ in range(50):
        n.convert_amount(D("1"), "EUR", date(2026, 1, 10))
    assert n.lookups == 1
    for day in (1, 2, 3):
        for _ in range(10):
            n.rate_for("GBP", date(2026, 2, day))
    assert n.lookups <= 4


# ---- root cause 2: roll-ups summed through float ----------------------------

def P(account, amount, period="2026-01", line=1):
    a = D(amount)
    return Posting(line=line, on=period_day(period), period=period, account=account,
                   description="", amount=a, original_amount=a, original_currency="USD",
                   rate=D(1))


def period_day(period):
    if "Q" in period:
        y, q = period.split("-Q")
        return date(int(y), 3 * int(q) - 2, 1)
    y, m = period.split("-")
    return date(int(y), int(m), 1)


def test_rollup_is_exact_decimal():
    ps = [P("Expenses:A:X", "123456789012.345678"), P("Expenses:A:Y", "0.000001"),
          P("Expenses:B", "0.1"), P("Expenses:B", "0.2", "2026-02"),
          P("Income:C", "-329.515", "2026-02")]
    t = aggregate(ps)
    assert t.balance("Expenses:A") == D("123456789012.345679")
    assert t.balance("Expenses:A", "2026-01") == D("123456789012.345679")
    assert t.balance("Expenses") == D("123456789012.645679")
    assert t.balance("Expenses:B") == D("0.3")
    assert t.balance("Income:C") == D("-329.515")
    assert t.grand("2026-02") == D("-329.315")
    assert t.grand() == D("123456788683.130679")
    for v in (t.balance("Expenses"), t.grand(), t.balance("Expenses:A", "2026-01")):
        assert isinstance(v, Decimal)


def test_rollup_function_direct():
    leaves = {"Expenses:A:X": {"2026-01": D("0.1")}, "Expenses:A:Y": {"2026-01": D("0.2")},
              "Expenses:B": {"2026-01": D("1e-7"), "2026-02": D("99999999999.999999")}}
    out = rollup(leaves)
    assert out["Expenses:A"] == {"2026-01": D("0.3")}
    assert out["Expenses"]["2026-01"] == D("0.3000001")
    assert out["Expenses"]["2026-02"] == D("99999999999.999999")
    assert out["Expenses:B"] == leaves["Expenses:B"]


def test_single_leaf_total_over_periods_is_exact():
    t = aggregate([P("Expenses:S", "199"), P("Expenses:S", "80.52", "2026-02"),
                   P("Expenses:S", "49.995", "2026-03")])
    assert t.balance("Expenses:S") == D("329.515")
    assert t.leaf("Expenses:S") == D("329.515")
    assert t.grand() == D("329.515")


def test_q1_totals_direct():
    book = load(LEDGER, RATES_TEXT)
    t = aggregate(book.postings)
    assert t.grand() == D("-3270.691325")
    assert t.balance("Expenses") == D("11265.558675")
    assert t.balance("Expenses:Office:Software") == D("329.515")
    assert t.balance("Expenses:Travel", "2026-03") == D("1609.684325")
    tq = aggregate(load(LEDGER, RATES_TEXT, period="quarter").postings)
    assert tq.balance("Expenses:Travel:Hotel") == D("2267.048525")


# ---- the formatter's rounding must be unchanged ----------------------------

@pytest.mark.parametrize("value,places,want", [
    ("0", 2, "0.00"), ("1.005", 2, "1.01"), ("2.675", 2, "2.68"), ("-2.675", 2, "-2.68"),
    ("0.125", 2, "0.13"), ("0.135", 2, "0.14"), ("-0.125", 2, "-0.13"),
    ("1.0049999", 2, "1.00"), ("1.004999999", 2, "1.00"), ("329.514999999", 2, "329.51"),
    ("329.515", 2, "329.52"), ("-329.5149999", 2, "-329.51"),
    ("-0.004", 2, "0.00"), ("-0.005", 2, "-0.01"), ("999.995", 2, "1,000.00"),
    ("1234567.891", 2, "1,234,567.89"), ("2.5", 0, "3"), ("3.5", 0, "4"), ("1.2345", 3, "1.235"),
    ("0.0000005", 6, "0.000001"), ("12.3449999", 2, "12.34"),
])
def test_format_money_rounding_unchanged(value, places, want):
    assert format_money(D(value), places) == want


def test_round_money_unchanged():
    assert round_money(D("0.125")) == D("0.13")
    assert round_money(D("1.0049999")) == D("1.00")
    assert round_money(D("-2.675")) == D("-2.68")
    assert round_money(D("2.5"), 0) == D("3")


def test_render_does_not_round_twice():
    row = ReportRow(label="Expenses:A", cells={"2026-01": D("1.0049999")}, total=D("1.0049999"))
    grand = ReportRow(label="TOTAL", cells={"2026-01": D("0.125")}, total=D("-0.125"),
                      is_total=True)
    rep = Report(title="T", base_currency="USD", periods=["2026-01"], rows=[row], grand=grand)
    assert render_csv(rep) == "account,2026-01,total\nExpenses:A,1.00,1.00\nTOTAL,0.13,-0.13\n"
    text = render_text(rep)
    assert "1.00" in text and "-0.13" in text and "1.01" not in text


def test_build_report_passes_exact_values():
    t = aggregate([P("Expenses:A:X", "0.1"), P("Expenses:A:Y", "0.2"),
                   P("Expenses:B", "0.004999")])
    rep = build_report(t)
    rows = {r.label: r for r in rep.rows}
    assert rows["Expenses:A"].total == D("0.3")
    assert rows["Expenses"].cells["2026-01"] == D("0.304999")
    assert rep.grand.total == D("0.304999")
    assert render_csv(rep).splitlines()[-1] == "TOTAL,0.30,0.30"


def test_format_options_and_locales_unchanged():
    assert format_money(D("-1234.5"), parens=True) == "(1,234.50)"
    assert format_money(D("3"), plus=True) == "+3.00"
    assert format_money(D("1234.5"), locale="de_DE") == "1.234,50"
    assert format_money(D("1234.5"), locale="de_CH") == "1'234.50"


# ---- other existing behaviour ------------------------------------------------

def test_depth_and_tag_reports():
    text = q1(tags=["trip-ber"], display_locale="de_DE")
    assert "TOTAL         1.472,19  1.472,19" in text
    deep = q1(depth=2, parens=True)
    assert deep.splitlines()[-1] == ("TOTAL         (1,643.01)    (521.93)  (1,105.76)"
                                     "   (3,270.69)")


def test_allocation_still_exact():
    from ledgerkit.normalize import allocate
    parts = allocate(D("100"), [("a", D(1)), ("b", D(1)), ("c", D(1))])
    assert [p for _, p in parts] == [D("33.333334"), D("33.333333"), D("33.333333")]
