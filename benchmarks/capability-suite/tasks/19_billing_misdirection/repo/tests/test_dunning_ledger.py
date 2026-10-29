from datetime import date
from decimal import Decimal

from meterbill.aging import aging, bucket_for
from meterbill.dunning import evaluate, late_fees_by_customer, parse_receivables, parse_schedule, suspended_customers
from meterbill.ledger import invoice_entries, trial_balance
from meterbill.money import Money

from .helpers import DATA, converter
from .test_render import _inv

RECV = ("invoice,customer,currency,amount,due,paid_on\n"
        "KC-1,C1,USD,100.00,2026-03-01,\n"
        "KC-2,C2,USD,1000.00,2026-02-01,\n"
        "KC-3,C3,USD,50.00,2026-03-01,2026-03-10\n")


def test_dunning_steps_and_fees():
    sched = parse_schedule((DATA / "dunning.toml").read_text())
    states = evaluate(parse_receivables(RECV), sched, date(2026, 3, 25), converter())
    by = {s.receivable.invoice: s for s in states}
    assert [s.action for s, _ in by["KC-1"].reached] == ["reminder", "late_fee"]
    assert by["KC-1"].fee == Money("5.00", "USD")
    assert by["KC-2"].suspended and by["KC-2"].fee == Money("15.00", "USD")
    assert [s.action for s, _ in by["KC-3"].reached] == ["reminder"]
    assert suspended_customers(states) == ["C2"]
    assert late_fees_by_customer(states)["C1"][0][1] == Money("5.00", "USD")


def test_aging_buckets():
    assert [bucket_for(d) for d in (0, 1, 30, 31, 61, 91)] == ["current", "1-30", "1-30", "31-60", "61-90", "90+"]
    rows = aging(parse_receivables(RECV), date(2026, 3, 25), converter())
    assert [r.invoice for r in rows] == ["KC-2", "KC-1"]


def test_journal_balances():
    inv = _inv()
    entries = invoice_entries(inv)
    assert all(e.balanced() for e in entries)
    tb = trial_balance(entries)
    assert tb["1200"]["USD"] == inv.total
    assert sum((v["USD"] for v in tb.values()), Money.zero("USD")) == 0
