"""Revenue schedule, quotes, alerts, lint, statements, export, credit notes,
commitments, anomalies, forecasts and the tax summary."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meterbill.alerts import Alert, check_alerts, parse_alerts
from meterbill.anomalies import gaps, spikes
from meterbill.commitments import parse_commitments, progress
from meterbill.credit_notes import credit_note, render_credit_note
from meterbill.errors import ConfigError
from meterbill.forecast import forecast
from meterbill.invoice import build_invoice
from meterbill.money import Money
from meterbill.periods import billing_period
from meterbill.quotes import compare, quote
from meterbill.revenue import schedule, schedule_total
from meterbill.tax_report import ec_sales_list, tax_summary

from .helpers import catalog, converter, customer, rec
from .test_invoice import ctx

D = Decimal
UTC = timezone.utc
USD = lambda a: Money(a, "USD")  # noqa: E731


def _records():
    return [rec("T01", "api_calls", 120000, "2026-02-03T10:00:00Z"),
            rec("T01", "api_calls", 60000, "2026-02-17T10:00:00Z"),
            rec("T01", "storage_gb", "80", "2026-02-20T10:00:00Z")]


def _starter_invoice(anchor=1, records=None):
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA", anchor_day=anchor)
    return build_invoice(ctx("T01,starter,2025-01-01\n"), c, "2026-02", records if records is not None else _records())


def test_revenue_schedule_sums_to_invoice():
    inv = _starter_invoice()
    sched = schedule(inv, _records(), catalog())
    assert list(sched) == ["2026-02"]
    assert schedule_total(sched, "USD") == inv.subtotal - inv.discount_total


def test_revenue_schedule_splits_months_for_mid_month_anchor():
    inv = _starter_invoice(anchor=10, records=[])
    sched = schedule(inv, [], catalog())
    # 10 Feb .. 9 Mar: 19 days in February, 9 in March of 28
    assert list(sched) == ["2026-02", "2026-03"]
    assert schedule_total(sched, "USD") == USD("49.00")
    assert sched["2026-02"] == USD("33.25")


def test_quote_matches_rating():
    q = quote(catalog(), "team", {"api_calls": 2500000, "seats": 7}, "USD", converter(), date(2026, 3, 10))
    assert q.base == USD("199.00")
    assert [ln.amount for ln in q.lines] == [USD("775.00"), USD("0.00"), USD("84.00")]
    assert q.total == USD("1058.00")


def test_compare_excludes_legacy_and_sorts():
    qs = compare(catalog(), {"api_calls": 50000}, "USD", converter(), date(2026, 3, 10))
    assert "legacy_basic" not in [q.plan for q in qs]
    assert qs[0].plan == "starter"
    assert [q.total.amount for q in qs] == sorted(q.total.amount for q in qs)


def test_alerts_fire_once_on_crossing():
    p = billing_period("2026-02", 1, "UTC")
    alerts = parse_alerts("customer,metric,threshold\nT01,api_calls,150000\nT01,storage_gb,500\n",
                          metrics=catalog().metrics)
    fired = check_alerts(alerts, _records(), p, catalog().metrics)
    assert len(fired) == 1 and fired[0].value == 180000
    with pytest.raises(ConfigError):
        parse_alerts("customer,metric,threshold\nT01,bogus,1\n", metrics=catalog().metrics)
    assert check_alerts([Alert("T01", "api_calls", D(10 ** 9))], _records(), p, catalog().metrics) == []


def test_credit_note_lists_changes():
    old = _starter_invoice()
    new = _starter_invoice(records=_records()[:1])
    cn = credit_note(old, new)
    assert cn.number == "CN-" + old.number
    assert cn.reversed_total == -old.total
    assert cn.net_change == new.total - old.total
    changed = cn.changed_lines()
    assert [c.description for c in changed] == ["API calls", "Storage"]
    assert "Net change USD" in render_credit_note(cn)


def test_commitment_progress():
    cs = parse_commitments("customer,contract,currency,minimum,start_cycle,end_cycle\n"
                           "T01,ENT-1,USD,1200.00,2026-01,2026-12\n")
    inv = _starter_invoice()
    pr = progress(cs[0], {"2026-02": inv, "2025-12": inv})
    assert pr.cycles_done == 1 and pr.spent == inv.subtotal
    assert pr.projected_shortfall() == USD("1200.00") - inv.subtotal * 12
    with pytest.raises(ConfigError):
        parse_commitments("customer,contract,currency,minimum,start_cycle,end_cycle\nT01,X,USD,1,2026-05,2026-01\n")


def test_spikes_and_gaps():
    p = billing_period("2026-02", 1, "UTC")
    recs = [rec("T01", "api_calls", 1000, datetime(2026, 2, d, 12, tzinfo=UTC)) for d in range(1, 29) if d not in (10, 11, 12, 13)]
    recs.append(rec("T01", "api_calls", 50000, datetime(2026, 2, 20, 13, tzinfo=UTC)))
    sp = spikes(recs, "T01", "api_calls", p)
    assert [s.day for s in sp] == [date(2026, 2, 20)]
    g = gaps(recs, "T01", p)
    assert [(x.first, x.days) for x in g] == [(date(2026, 2, 10), 4)]


def test_forecast_extrapolates_sum_metrics():
    c = customer(id="T01", timezone="UTC", jurisdiction="US-CA")
    p = billing_period("2026-02", 1, "UTC")
    fc = forecast(ctx("T01,starter,2025-01-01\n"), c, p, _records(), datetime(2026, 2, 15, tzinfo=UTC))
    api = fc.lines[0]
    assert api.so_far == 120000 and api.projected == 240000
    assert fc.base == USD("49.00")
    with pytest.raises(ValueError):
        forecast(ctx("T01,starter,2025-01-01\n"), c, p, [], datetime(2026, 3, 15, tzinfo=UTC))


def test_tax_summary_and_ec_list():
    de = customer(id="T02", timezone="Europe/Berlin", currency="EUR", jurisdiction="DE", tax_id="DE1")
    inv_de = build_invoice(ctx("T02,team_eu,2025-01-01\n"), de, "2026-02", [])
    inv_us = _starter_invoice()
    totals = tax_summary([inv_us, inv_de])
    assert [t.code for t in totals] == ["DE", "US-CA"]
    assert totals[0].reverse_charged["EUR"] == Money("185.00", "EUR")
    assert ec_sales_list([inv_us, inv_de]) == [("T02", "DE1", Money("185.00", "EUR"))]
