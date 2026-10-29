"""Customer notification e-mails."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meterbill.alerts import Alert, Fired
from meterbill.dunning import DunningState, Receivable, Step
from meterbill.invoice import build_invoice
from meterbill.money import Money
from meterbill.notifications import (Notification, invoice_issued, notifications_for_run, payment_reminder,
                                     suspension_notice, usage_alert, wrap_paragraphs)
from meterbill.pipeline import run_billing

from .helpers import DATA, catalog, customer, rec
from .test_invoice import ctx

CUST = customer(id="C05", name="Eastgate Studio KK", email="keiri@eastgate.example")


def receivable():
    return Receivable("KC-2026-01-C05", "C05", Money("15210", "JPY"), date(2026, 3, 11))


def state(*actions, fee=None):
    st = DunningState(receivable(), fee=fee)
    for days, action in actions:
        st.reached.append((Step(days, action), date(2026, 3, 11).fromordinal(date(2026, 3, 11).toordinal() + days)))
    return st


def make_invoice():
    c = customer(id="T01", name="Test Co", email="t@test.example", jurisdiction="US-CA")
    records = [rec("T01", "api_calls", 150000, "2026-02-10T12:00:00Z")]
    return build_invoice(ctx("T01,starter,2025-01-01\n"), c, "2026-02", records)


def test_wrap_limits_width_and_keeps_tables():
    text = "word " * 60 + "\n\n  row   1.00\n  row   2.00"
    out = wrap_paragraphs(text)
    assert all(len(ln) <= 72 for ln in out.split("\n"))
    assert out.endswith("  row   1.00\n  row   2.00")


def test_invoice_issued_content():
    n = invoice_issued(make_invoice())
    assert isinstance(n, Notification) and n.to == "t@test.example"
    assert n.subject == "Invoice KC-2026-02-T01 from Kettle Cloud: 74.00 USD due 2026-03-31"
    assert "Amount due" in n.body and "74.00 USD" in n.body
    assert all(len(ln) <= 72 for ln in n.body.split("\n"))
    assert n.body.rstrip().endswith("billing@kettlecloud.example")


def test_deterministic():
    inv = make_invoice()
    assert invoice_issued(inv).render() == invoice_issued(inv).render()
    assert invoice_issued(inv).render().startswith("To: t@test.example\nSubject: Invoice ")


def test_reminder_first_and_with_fee():
    st = state((7, "reminder"))
    n = payment_reminder(st, CUST)
    assert "first reminder" in n.body and "15,210 JPY" in n.subject
    assert "late fee" in n.body  # generic warning
    st = state((7, "reminder"), (21, "late_fee"), fee=Money("228", "JPY"))
    n = payment_reminder(st, CUST)
    assert "late fee of 228 JPY will be added" in n.body


def test_reminder_requires_reminder_step():
    with pytest.raises(ValueError):
        payment_reminder(state((21, "late_fee")), CUST)


def test_second_reminder_wording():
    st = state((7, "reminder"), (14, "reminder"))
    assert "reminder number 2" in payment_reminder(st, CUST).body


def test_suspension_notice():
    st = state((7, "reminder"), (45, "suspend"))
    n = suspension_notice(st, CUST)
    assert "suspended" in n.subject and "C05" in n.body and "2026-04-25" in n.body
    with pytest.raises(ValueError):
        suspension_notice(state((7, "reminder")), CUST)


def test_usage_alert():
    f = Fired(Alert("C05", "storage_gb", Decimal("100")), datetime(2026, 3, 5, 12, tzinfo=timezone.utc),
              Decimal("101.5"), "ev-1")
    n = usage_alert(f, CUST, catalog().metrics)
    assert "101.500 GB" in n.subject
    assert "threshold of 100.000 GB" in n.body and "2026-03-05T12:00:00Z" in n.body and "ev-1" in n.body
    assert all(len(ln) <= 72 for ln in n.body.split("\n"))


def test_notifications_for_run_sample_data():
    run = run_billing(DATA, "2026-03", customers=["C05"])
    notes = notifications_for_run(run)
    assert notes[0].subject.startswith("Invoice KC-2026-03-C05")
    assert any(n.subject.startswith("Reminder") for n in notes)
