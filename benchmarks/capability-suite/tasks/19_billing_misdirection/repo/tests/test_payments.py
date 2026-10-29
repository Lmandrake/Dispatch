"""Payment parsing and allocation to receivables."""

from datetime import date

import pytest

from meterbill.dunning import parse_receivables
from meterbill.errors import ConfigError
from meterbill.money import Money
from meterbill.payments import allocate_payments, parse_payments, render_allocation_report

REC = """invoice,customer,currency,amount,due,paid_on
A-1,C01,USD,100.00,2026-03-10,
A-2,C01,USD,50.00,2026-02-10,
A-3,C01,EUR,80.00,2026-02-01,
A-4,C01,USD,10.00,2026-01-01,2026-01-05
"""


def pays(body):
    return parse_payments("payment_id,customer,currency,amount,received,reference\n" + body)


def run(body):
    return allocate_payments(parse_receivables(REC), pays(body))


def test_parse_basic():
    p = pays("P1,c01,USD,12.50,2026-03-01,ref x\n")[0]
    assert p.customer == "C01" and p.amount == Money("12.50", "USD")
    assert p.received == date(2026, 3, 1) and p.reference == "ref x"


@pytest.mark.parametrize("row", [
    "P1,C01,USD,-5,2026-03-01,",
    "P1,C01,USD,1.234,2026-03-01,",
    "P1,C01,USD,abc,2026-03-01,",
    "P1,C01,USD,5,03/01/2026,",
    "P1,C01,XXX,5,2026-03-01,",
])
def test_parse_rejects_bad_rows(row):
    with pytest.raises(ConfigError):
        pays(row)


def test_parse_duplicate_id():
    with pytest.raises(ConfigError, match="duplicate payment id"):
        pays("P1,C01,USD,5,2026-03-01,\nP1,C01,USD,6,2026-03-02,\n")


def test_missing_column():
    with pytest.raises(ConfigError):
        parse_payments("payment_id,customer\nP1,C01\n")


def test_oldest_due_first_and_partial():
    res = run("P1,C01,USD,70.00,2026-03-05,\n")
    a2, a1 = res.status("A-2"), res.status("A-1")
    assert a2.state == "settled" and a2.allocated == Money("50.00", "USD")
    assert a1.state == "partial" and a1.outstanding == Money("80.00", "USD")
    assert not res.unapplied


def test_overpayment_becomes_unapplied_cash():
    res = run("P1,C01,USD,200.00,2026-03-05,\n")
    assert res.status("A-1").state == "settled" and res.status("A-2").state == "settled"
    assert [u.amount for u in res.unapplied] == [Money("50.00", "USD")]
    assert res.unapplied[0].reason == "overpayment"
    assert res.unapplied_total("C01", "USD") == Money("50.00", "USD")


def test_paid_receivable_takes_nothing_and_has_no_outstanding():
    res = run("P1,C01,USD,1000.00,2026-03-05,\n")
    st = res.status("A-4")
    assert st.state == "paid" and not st.allocations and not st.outstanding


def test_currency_mismatch_not_converted():
    res = run("P1,C01,EUR,100.00,2026-03-05,\n")
    assert res.status("A-3").state == "settled"
    assert res.unapplied_total("C01", "EUR") == Money("20.00", "EUR")
    res = run("P1,C01,GBP,10.00,2026-03-05,\n")
    assert res.unapplied[0].reason == "no open GBP receivable for C01"


def test_unknown_customer_is_unapplied():
    res = run("P1,C99,USD,10.00,2026-03-05,\n")
    assert len(res.unapplied) == 1 and not res.allocations()


def test_payment_order_is_by_date_then_id():
    res = run("P2,C01,USD,30.00,2026-03-02,\nP1,C01,USD,30.00,2026-03-02,\n")
    a2 = res.status("A-2")
    assert [a.payment_id for a in a2.allocations] == ["P1", "P2"]
    assert a2.allocations[1].amount == Money("20.00", "USD")


def test_outstanding_total_and_report():
    res = run("P1,C01,USD,70.00,2026-03-05,\nP2,C01,EUR,100.00,2026-03-06,\n")
    assert res.outstanding_total("C01", "USD") == Money("80.00", "USD")
    text = render_allocation_report(res)
    assert "A-1" in text and "partial" in text
    assert "P2" in text and "overpayment" in text
    assert text.endswith("\n")
    assert render_allocation_report(res) == text


def test_empty_payments():
    res = allocate_payments(parse_receivables(REC), [])
    assert [s.state for s in res.statuses] == ["open", "open", "open", "paid"]
    assert "none" in render_allocation_report(res)
