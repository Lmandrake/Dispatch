"""Hidden tests for 19_billing_misdirection (files sit at the workdir root).

Data and goldens come from hidden_data.json, not from the repo, so edits to
data/ or tests/golden/ do not change what is checked.
"""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from meterbill.catalog import parse_catalog
from meterbill.customers import Customer
from meterbill.discounts import Redemption, parse_coupons
from meterbill.fx import Converter, parse_rates
from meterbill.invoice import BillingContext, build_invoice, invoice_check
from meterbill.meters.csv_feed import read_csv_feed
from meterbill.meters.ingest import merge
from meterbill.meters.records import UsageRecord
from meterbill.money import Money
from meterbill.periods import billing_period
from meterbill.pipeline import run_billing
from meterbill.pricing import parse_price, rate
from meterbill.proration import prorate
from meterbill.reconcile import render_recon
from meterbill.render import render
from meterbill.render.fmt import format_amount
from meterbill.subscriptions import Segment, parse_subscriptions
from meterbill.tax import TaxTable, parse_tax
from meterbill.usage import assign

HERE = Path(__file__).resolve().parent
DOC = json.loads((HERE / "hidden_data.json").read_text(encoding="utf-8"))
D = Decimal
UTC = timezone.utc
CYCLES = {"mar2026": "2026-03", "oct2026": "2026-10"}
PREV = {"mar2026": "2026-02", "oct2026": "2026-09"}
FIRST = {"mar2026": "2026-01", "oct2026": "2026-08"}
FMT = {"txt": "text", "csv": "csv", "json": "json"}


@pytest.fixture(scope="session")
def data_dirs(tmp_path_factory):
    out = {}
    for name, files in DOC["datasets"].items():
        root = tmp_path_factory.mktemp(name)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        out[name] = root
    return out


_RUNS = {}


def run_of(data_dirs, name):
    if name not in _RUNS:
        _RUNS[name] = run_billing(data_dirs[name], CYCLES[name])
    return _RUNS[name]


_PREV_RUNS = {}


def produced(data_dirs, name, fname):
    if fname.startswith("close-"):
        return _close(data_dirs, name)[1][fname[len("close-"):]]
    if fname.startswith("restate-"):
        from meterbill.restatement import render_journal, render_revenue, render_summary, restate
        res = restate(data_dirs[name], FIRST[name], CYCLES[name])
        kind = fname.split("-", 1)[1].split(".")[0]
        return {"summary": render_summary, "journal": render_journal, "revenue": render_revenue}[kind](res)
    if fname.startswith("rebill."):
        from meterbill.rebill import rebill, render_rebill_csv, render_rebill_text
        adj = rebill(data_dirs[name])
        return render_rebill_text(adj) if fname.endswith(".txt") else render_rebill_csv(adj)
    if f"-{PREV[name]}-" in fname:
        if name not in _PREV_RUNS:
            _PREV_RUNS[name] = run_billing(data_dirs[name], PREV[name])
        cid = fname.rsplit(".", 1)[0].split("-")[-1]
        return render(_PREV_RUNS[name].invoice(cid), "text")
    r = run_of(data_dirs, name)
    if fname.startswith("recon-"):
        return render_recon(CYCLES[name], r.reconciliation(), r.ingested)
    stem, ext = fname.rsplit(".", 1)
    cid = stem.split("-")[-1]
    return render(r.invoice(cid), FMT[ext])


GOLDEN_CASES = [(ds, f) for ds in ("mar2026", "oct2026") for f in sorted(DOC["goldens"][ds])]


# ---------------------------------------------------------------- goldens
@pytest.mark.parametrize("ds,fname", GOLDEN_CASES, ids=[f"{d}/{f}" for d, f in GOLDEN_CASES])
def test_golden(data_dirs, ds, fname):
    assert produced(data_dirs, ds, fname) == DOC["goldens"][ds][fname]


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_every_invoice_adds_up(data_dirs, ds):
    for inv in run_of(data_dirs, ds).invoices:
        assert invoice_check(inv) == [], inv.number


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_single_customer_runs_match_full_run(data_dirs, ds):
    full = run_of(data_dirs, ds)
    for inv in full.invoices:
        alone = run_billing(data_dirs[ds], CYCLES[ds], customers=[inv.customer.id]).invoice(inv.customer.id)
        assert render(alone, "json") == render(inv, "json"), inv.number


# ---------------------------------------------------------------- cause 1: period ends at local midnight
@pytest.mark.parametrize("cycle,anchor,tz,end_utc,hours", [
    ("2026-03", 1, "America/New_York", datetime(2026, 4, 1, 4, 0, tzinfo=UTC), 743),
    ("2026-03", 1, "Europe/Berlin", datetime(2026, 3, 31, 22, 0, tzinfo=UTC), 743),
    ("2026-03", 5, "America/Denver", datetime(2026, 4, 5, 6, 0, tzinfo=UTC), 743),
    ("2026-10", 1, "Europe/Berlin", datetime(2026, 10, 31, 23, 0, tzinfo=UTC), 745),
    ("2026-10", 1, "Australia/Sydney", datetime(2026, 10, 31, 13, 0, tzinfo=UTC), 743),
    ("2026-10", 25, "Europe/London", datetime(2026, 11, 25, 0, 0, tzinfo=UTC), 745),
    ("2026-10", 12, "America/Los_Angeles", datetime(2026, 11, 12, 8, 0, tzinfo=UTC), 745),
    ("2026-04", 1, "Australia/Sydney", datetime(2026, 4, 30, 14, 0, tzinfo=UTC), 721),
])
def test_period_end_is_local_midnight_across_dst(cycle, anchor, tz, end_utc, hours):
    p = billing_period(cycle, anchor, tz)
    assert p.end_utc == end_utc
    assert p.hours() == hours
    nxt = billing_period(f"{p.end.year:04d}-{p.end.month:02d}", anchor, tz)
    assert nxt.start_utc == p.end_utc


@pytest.mark.parametrize("cycle,anchor,tz", [
    ("2026-02", 1, "UTC"), ("2026-03", 15, "Asia/Tokyo"), ("2026-01", 1, "America/New_York"),
    ("2026-07", 10, "Europe/Berlin"),
])
def test_period_without_dst_change_unchanged(cycle, anchor, tz):
    p = billing_period(cycle, anchor, tz)
    assert p.hours() == p.days * 24


def _rec(cust, metric, qty, at, eid):
    return UsageRecord(eid, cust, metric, D(str(qty)), at, "t", 1)


def test_record_twenty_minutes_into_next_month_is_not_billed_this_month():
    p = billing_period("2026-03", 1, "America/New_York")
    just_after = datetime(2026, 4, 1, 4, 20, tzinfo=UTC)     # 00:20 EDT on 1 April
    just_before = datetime(2026, 4, 1, 3, 50, tzinfo=UTC)    # 23:50 EDT on 31 March
    assert not p.contains(just_after)
    assert p.contains(just_before)
    pu = assign([_rec("C1", "api_calls", 5, just_after, "a"), _rec("C1", "api_calls", 7, just_before, "b")],
                p, [Segment("team", p.start, p.end)])
    assert pu.outside == 1 and pu.billed_count() == 1


def test_record_late_on_last_day_after_dst_end_is_billed():
    p = billing_period("2026-10", 1, "Europe/Berlin")
    late = datetime(2026, 10, 31, 22, 40, tzinfo=UTC)        # 23:40 CET on 31 October
    assert p.contains(late)


# ---------------------------------------------------------------- cause 2: up_to is inclusive
VOL = parse_price({"model": "volume", "tiers": [
    {"up_to": 10, "unit_price": "12.00"}, {"up_to": 25, "unit_price": "10.00"},
    {"up_to": "inf", "unit_price": "8.00"}]}, "t")
VOL_FEE = parse_price({"model": "volume", "tiers": [
    {"up_to": 100, "unit_price": "1", "flat_fee": "50"}, {"up_to": "inf", "unit_price": "0.5", "flat_fee": "10"}]}, "t")


@pytest.mark.parametrize("qty,amount", [
    (1, "12"), (9, "108"), (10, "120"), (11, "110"), (24, "240"), (25, "250"), (26, "208"), (40, "320"),
])
def test_volume_tier_bound_inclusive(qty, amount):
    assert rate(VOL, qty).amount == D(amount)


def test_volume_bound_with_flat_fee_and_fractional_quantities():
    assert rate(VOL_FEE, 100).amount == D("150")
    assert rate(VOL_FEE, D("100.5")).amount == D("60.25")
    assert rate(VOL, D("10.0")).amount == D("120")
    assert rate(VOL, D("25.000")).amount == D("250")


@pytest.mark.parametrize("plan,metric,qty,amount", [
    ("team", "seats", 25, "250"),
    ("business", "seats", 20, "220"),
    ("business", "seats", 50, "450"),
    ("business", "api_calls", 1000000, "350"),
    ("business_eu", "seats", 50, "415"),
    ("team_eu", "seats", 10, "110"),
])
def test_catalogue_volume_bounds(plan, metric, qty, amount):
    cat = parse_catalog(DOC["datasets"]["mar2026"]["catalog.toml"])
    assert cat.plan(plan).rate(metric, qty).amount == D(amount)


def test_graduated_bound_unchanged():
    cat = parse_catalog(DOC["datasets"]["mar2026"]["catalog.toml"])
    r = cat.plan("team").rate("api_calls", 1000000)
    assert r.amount == D("400") and len(r.slices) == 1
    r = cat.plan("team").rate("api_calls", 1000001)
    assert r.amount == D("400.00025")


# ---------------------------------------------------------------- cause 3: proration uses the period's days
@pytest.mark.parametrize("cycle,anchor,seg_start,seg_end,days,period_days", [
    ("2026-03", 15, date(2026, 4, 2), date(2026, 4, 15), 13, 31),
    ("2026-03", 15, date(2026, 3, 15), date(2026, 4, 2), 18, 31),
    ("2026-02", 15, date(2026, 3, 2), date(2026, 3, 15), 13, 28),
    ("2026-01", 28, date(2026, 2, 10), date(2026, 2, 28), 18, 31),
    ("2026-03", 28, date(2026, 4, 10), date(2026, 4, 28), 18, 31),
    ("2026-10", 15, date(2026, 11, 3), date(2026, 11, 15), 12, 31),
    ("2026-03", 1, date(2026, 3, 12), date(2026, 4, 1), 20, 31),
])
def test_proration_denominator_is_billing_period_days(cycle, anchor, seg_start, seg_end, days, period_days):
    p = billing_period(cycle, anchor, "UTC")
    pr = prorate(D("199.00"), Segment("team", seg_start, seg_end), p)
    assert (pr.days, pr.period_days) == (days, period_days)
    assert pr.fraction == Fraction(days, period_days)
    assert pr.amount == (D("199.00") * days / period_days).quantize(D("0.00000001"))


def test_prorated_segments_of_a_change_add_up_to_one_fee():
    p = billing_period("2026-02", 15, "America/Chicago")
    a = prorate(D("100"), Segment("team", date(2026, 2, 15), date(2026, 3, 2)), p)
    b = prorate(D("100"), Segment("team", date(2026, 3, 2), date(2026, 3, 15)), p)
    assert a.fraction + b.fraction == 1


# ---------------------------------------------------------------- cause 4: coupons before tax
def _ctx(subs, ds="mar2026", **kw):
    files = DOC["datasets"][ds]
    cat = parse_catalog(files["catalog.toml"])
    return BillingContext(
        catalog=cat,
        subscriptions=parse_subscriptions("customer,plan,effective\n" + subs, catalog=cat),
        tax=TaxTable(parse_tax(files["tax.toml"])),
        converter=Converter(parse_rates(files["fx_rates.csv"])),
        coupons=parse_coupons(files["coupons.toml"]), **kw)


def _cust(**kw):
    base = dict(id="T01", name="Test", timezone="UTC", anchor_day=1, currency="USD", jurisdiction="US-NY")
    base.update(kw)
    return Customer(**base)


@pytest.mark.parametrize("juris,coupon,expected_tax", [
    ("US-NY", "WELCOME10", "3.91"),     # 44.10 * 8.875%
    ("US-TX", "WELCOME10", "2.76"),     # per-line on the discounted lines
    ("US-CO", "BASE20", "1.14"),        # 39.20 * 2.9%
    ("US-NY", "PARTNER50", "0.00"),     # discount capped at the subtotal
])
def test_tax_is_charged_on_the_discounted_amount(juris, coupon, expected_tax):
    c = _cust(jurisdiction=juris)
    ctx = _ctx("T01,starter,2025-01-01\n", redemptions=[Redemption("T01", coupon, "2026-02")])
    inv = build_invoice(ctx, c, "2026-02", [])
    assert inv.subtotal == Money("49.00", "USD")
    assert inv.tax.taxable == inv.subtotal - inv.discount_total
    assert inv.tax.tax == Money(expected_tax, "USD")
    assert inv.total == inv.subtotal - inv.discount_total + inv.tax.tax
    assert invoice_check(inv) == []


def test_credit_still_applied_after_tax():
    from meterbill.credits import parse_credits
    grants = parse_credits("customer,grant_id,currency,amount,granted,expires\nT01,G1,USD,10.00,2026-01-01,\n")
    ctx = _ctx("T01,starter,2025-01-01\n", redemptions=[Redemption("T01", "WELCOME10", "2026-02")], grants=grants)
    inv = build_invoice(ctx, _cust(), "2026-02", [])
    assert inv.tax.taxable == Money("44.10", "USD")
    assert inv.total == Money("48.01", "USD")
    assert inv.amount_due == Money("38.01", "USD")


# ---------------------------------------------------------------- cause 5: FX memo must not change results
RATES = ("effective,currency,per_usd\n"
         "2026-03-01,EUR,0.9210\n2026-03-16,EUR,0.9234\n2026-04-01,EUR,0.9251\n"
         "2026-03-01,GBP,0.7915\n2026-03-26,GBP,0.7948\n2026-03-01,CHF,0.8790\n")


def _fresh(on, src, dst):
    return Converter(parse_rates(RATES)).cross_rate(src, dst, on)


@pytest.mark.parametrize("src,dst", [("EUR", "USD"), ("GBP", "USD"), ("EUR", "GBP"), ("GBP", "EUR"),
                                     ("USD", "EUR"), ("EUR", "CHF"), ("CHF", "GBP")])
def test_cross_rate_independent_of_lookup_history(src, dst):
    days = [date(2026, 3, d) for d in (2, 31, 15, 16, 27, 25, 1)] + [date(2026, 4, 3)]
    shared = Converter(parse_rates(RATES))
    for day in days:
        assert shared.cross_rate(src, dst, day) == _fresh(day, src, dst), day
    for day in reversed(days):
        assert shared.cross_rate(src, dst, day) == _fresh(day, src, dst), day


def test_cross_rate_values():
    c = Converter(parse_rates(RATES))
    assert c.cross_rate("EUR", "USD", date(2026, 3, 5)) == D("1.0857763301")
    assert c.cross_rate("EUR", "USD", date(2026, 3, 20)) == D("1.0829542993")
    assert c.cross_rate("GBP", "EUR", date(2026, 3, 20)) == D("1.1666456096")
    assert c.cross_rate("GBP", "EUR", date(2026, 3, 27)) == D("1.1618017111")


def test_convert_after_other_conversions():
    c = Converter(parse_rates(RATES))
    c.convert(Money("100", "EUR"), "USD", date(2026, 3, 2))
    c.convert(Money("100", "GBP"), "EUR", date(2026, 3, 2))
    c.convert(Money("100", "GBP"), "EUR", date(2026, 3, 20))
    assert c.convert(Money("100", "EUR"), "USD", date(2026, 4, 2)) == Money("108.09642201", "USD")
    assert c.convert(Money("100", "GBP"), "EUR", date(2026, 3, 30)) == Money("116.18017111", "EUR")


# ---------------------------------------------------------------- cause 6: gateway CSV parsing
HDR = "event_id,customer,metric,quantity,timestamp,note\n"


def test_quoted_comma_in_note_is_kept():
    res = read_csv_feed(HDR + 'e1,C01,api_calls,3500,2026-03-17T14:02:11Z,"replayed by support, ticket 4471"\n', "g.csv")
    assert res.rejects == []
    assert [(r.event_id, r.quantity, r.note) for r in res.records] == [("e1", D(3500), "replayed by support, ticket 4471")]


def test_doubled_quotes_and_several_commas():
    res = read_csv_feed(HDR + 'e1,C07,api_calls,15500,2026-10-07T18:00:00Z,"customer said ""urgent"", call back"\n'
                              'e2,C07,api_calls,4400,2026-10-08T18:00:00Z,"retry, 503, then ok"\n'
                              'e3,C10,api_calls,7700,2026-10-09T13:00:00Z,"he said ""fine"""\n', "g.csv")
    assert res.rejects == []
    assert [r.note for r in res.records] == ['customer said "urgent", call back', "retry, 503, then ok", 'he said "fine"']


def test_quoted_field_in_other_column_order():
    text = ('timestamp,event_id,customer,metric,quantity,note\n'
            '2026-03-22T05:45:00Z,e9,C08,api_calls,18250,"manual, approved by J. Ortiz"\n')
    res = read_csv_feed(text, "g.csv")
    assert len(res.records) == 1 and res.records[0].customer == "C08" and res.records[0].quantity == 18250


def test_quoted_newline_in_note():
    res = read_csv_feed(HDR + 'e1,C01,api_calls,10,2026-03-02T10:00:00Z,"line one\nline two"\n'
                              'e2,C01,api_calls,20,2026-03-02T11:00:00Z,\n', "g.csv")
    assert [r.quantity for r in res.records] == [10, 20]
    assert res.records[0].note == "line one\nline two"


def test_row_with_too_many_fields_is_rejected_not_dropped():
    res = read_csv_feed(HDR + "e1,C01,api_calls,10,2026-03-02T10:00:00Z,note,extra\n"
                              "e2,C01,api_calls,20,2026-03-02T11:00:00Z,\n", "g.csv")
    assert [r.event_id for r in res.records] == ["e2"]
    assert len(res.rejects) == 1 and res.rejects[0].line == 2
    assert "fields" in res.rejects[0].reason


def test_too_few_fields_still_rejected():
    res = read_csv_feed(HDR + "e1,C01,api_calls,10\n", "g.csv")
    assert res.records == [] and len(res.rejects) == 1


def test_feed_record_counts(data_dirs):
    r = run_of(data_dirs, "mar2026")
    assert len(r.ingested.records) == 3589
    assert len(r.ingested.rejects) == 8 and r.ingested.replays == 4
    notes = {x.note for x in r.ingested.records if x.note}
    assert "replayed by support, ticket 4471" in notes and 'backfill, see "INC-2207"' in notes


# ---------------------------------------------------------------- renderers stay pure formatters
@pytest.mark.parametrize("amount,cur,text", [
    ("1234.50", "USD", "1,234.50"), ("-0.05", "USD", "-0.05"), ("15210", "JPY", "15,210"),
    ("0.125", "KWD", "0.125"), ("1000000.00", "SEK", "1,000,000.00"), ("2.68", "EUR", "2.68"),
])
def test_format_amount_is_identity_on_rounded_amounts(amount, cur, text):
    assert format_amount(Money(amount, cur)) == text
    assert format_amount(Money(amount, cur), strict=True) == text


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_rendered_amounts_are_invoice_fields(data_dirs, ds):
    for inv in run_of(data_dirs, ds).invoices:
        doc = json.loads(render(inv, "json"))
        assert D(doc["subtotal"]) == inv.subtotal.amount
        assert D(doc["total"]) == inv.total.amount
        assert D(doc["tax"]["amount"]) == inv.tax.tax.amount
        assert D(doc["amount_due"]) == inv.amount_due.amount
        assert len(doc["lines"]) == len(inv.lines)
        for ln, d in zip(inv.lines, doc["lines"]):
            assert D(d["amount"]) == ln.amount.amount


# ---------------------------------------------------------------- existing behaviour still works
def test_existing_feed_rejects_still_reported(data_dirs):
    reasons = [x.reason for x in run_of(data_dirs, "mar2026").ingested.rejects]
    assert any("offset" in x for x in reasons)
    assert any("negative" in x for x in reasons)
    assert any("unknown customer C99" in x for x in reasons)
    assert any("conflicts" in x for x in reasons)
    assert any("float" in x for x in reasons)
    assert any("unterminated" in x for x in reasons)


def test_merge_replay_rules_unchanged():
    a = read_csv_feed(HDR + "e1,C01,api_calls,100,2026-03-02T10:00:00Z,\n", "a.csv")
    b = read_csv_feed(HDR + 'e1,C01,api_calls,100,2026-03-02T10:00:00Z,"same, again"\n', "b.csv")
    ing = merge([a, b], customers={"C01"}, metrics={"api_calls"})
    assert len(ing.records) == 1 and ing.replays == 1 and ing.rejects == []


def test_reverse_charge_unchanged(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C02")
    assert inv.tax.reverse_charged and inv.tax.tax == Money("0", "EUR")


def test_unbilled_after_subscription_end(data_dirs):
    inv = run_of(data_dirs, "oct2026").invoice("C08")
    assert inv.usage_counts["unbilled"] > 0
    assert any("not billed" in n for n in inv.notes)


def test_suspension_and_late_fee_unchanged(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C12")
    assert inv.late_fees == Money("11.10", "USD")


def test_journal_still_balances(data_dirs):
    from meterbill.ledger import journal
    for e in journal(run_of(data_dirs, "oct2026").invoices):
        assert e.balanced(), e.ref


# ---------------------------------------------------------------- cause 7: credit expiry is exclusive
def test_credit_unusable_on_its_expiry_day():
    from meterbill.credits import parse_credits, usable_grants
    gs = parse_credits("customer,grant_id,currency,amount,granted,expires\n"
                       "C1,G1,USD,10,2026-01-01,2026-03-01\nC1,G2,USD,10,2026-03-01,\n")
    assert [g.grant_id for g in usable_grants(gs, "C1", date(2026, 2, 28))] == ["G1"]
    assert [g.grant_id for g in usable_grants(gs, "C1", date(2026, 3, 1))] == ["G2"]
    assert gs[0].usable_on(date(2026, 1, 1)) and not gs[0].usable_on(date(2026, 3, 1))


def test_expired_credit_not_applied_on_issue_day(data_dirs):
    inv = run_billing(data_dirs["mar2026"], "2026-02", customers=["C04"]).invoice("C04")
    assert inv.credits == [] or all(not u.applied for u in inv.credits)
    assert inv.amount_due == inv.total


# ---------------------------------------------------------------- cause 8: a late fee is billed once
def test_late_fee_not_billed_twice(data_dirs):
    feb = run_billing(data_dirs["mar2026"], "2026-02", customers=["C06"]).invoice("C06")
    mar = run_of(data_dirs, "mar2026").invoice("C06")
    assert feb.late_fees == Money("52.06", "SEK")
    assert mar.late_fees == Money("0", "SEK")


def test_evaluate_since_skips_fees_already_billed():
    from meterbill.dunning import evaluate, parse_receivables, parse_schedule
    sched = parse_schedule(DOC["datasets"]["mar2026"]["dunning.toml"])
    recv = parse_receivables("invoice,customer,currency,amount,due,paid_on\nKC-1,C1,USD,1000.00,2026-01-01,\n")
    conv = Converter(parse_rates(DOC["datasets"]["mar2026"]["fx_rates.csv"]))
    first = evaluate(recv, sched, date(2026, 2, 1), conv, since=date(2026, 1, 1))
    again = evaluate(recv, sched, date(2026, 3, 1), conv, since=date(2026, 2, 1))
    assert first[0].fee == Money("15.00", "USD")
    assert again[0].fee is None and again[0].suspended


# ---------------------------------------------------------------- cause 9: jurisdiction precedence
@pytest.mark.parametrize("billing,service,override,expected", [
    ("GB", "US-TX", "", "US-TX"),
    ("GB", "", "", "GB"),
    ("US-NY", "US-CA", "US-CO", "US-CO"),
    ("US-NY", "XX", "", "US-NY"),
    ("DE", "SE", "", "SE"),
    ("GB", "US-WA", "", "GB"),
])
def test_jurisdiction_precedence(billing, service, override, expected):
    from meterbill.jurisdiction import resolve_jurisdiction
    table = TaxTable(parse_tax(DOC["datasets"]["mar2026"]["tax.toml"]))
    c = _cust(jurisdiction=billing, service_region=service, tax_override=override)
    assert resolve_jurisdiction(c, table) == expected


def test_service_region_taxed(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C14")
    assert inv.tax.rule.code == "US-TX"


# ---------------------------------------------------------------- cause 10: JSON-lines ISO offsets
@pytest.mark.parametrize("ts,expected", [
    ("2026-03-31T23:30:00+02:00", datetime(2026, 3, 31, 21, 30, tzinfo=UTC)),
    ("2026-04-01T00:30:00+02:00", datetime(2026, 3, 31, 22, 30, tzinfo=UTC)),
    ("2026-10-31T23:15:00-05:00", datetime(2026, 11, 1, 4, 15, tzinfo=UTC)),
    ("2026-03-01T00:00:00Z", datetime(2026, 3, 1, tzinfo=UTC)),
    (1772323200, datetime(2026, 3, 1, tzinfo=UTC)),
])
def test_jsonl_timestamp_offsets(ts, expected):
    from meterbill.meters.jsonl_feed import read_jsonl_feed
    line = json.dumps({"id": "s1", "customer": "C02", "metric": "storage_gb", "value": "1", "ts": ts})
    res = read_jsonl_feed(line + "\n", "s.jsonl")
    assert res.rejects == [] and res.records[0].at == expected


def test_jsonl_iso_without_offset_rejected():
    from meterbill.meters.jsonl_feed import read_jsonl_feed
    line = json.dumps({"id": "s1", "customer": "C02", "metric": "storage_gb", "value": "1", "ts": "2026-03-01T10:00:00"})
    res = read_jsonl_feed(line + "\n", "s.jsonl")
    assert res.records == [] and len(res.rejects) == 1


# ---------------------------------------------------------------- cause 11: replays across feed files
def test_replay_across_files_dropped_and_conflict_rejected():
    a = read_csv_feed(HDR + "e1,C01,api_calls,100,2026-03-02T10:00:00Z,\ne2,C01,api_calls,5,2026-03-02T10:00:00Z,\n", "a.csv")
    b = read_csv_feed(HDR + "e1,C01,api_calls,100,2026-03-02T10:00:00Z,\ne2,C01,api_calls,6,2026-03-02T10:00:00Z,\n", "b.csv")
    ing = merge([a, b], customers={"C01"}, metrics={"api_calls"})
    assert [r.quantity for r in ing.records] == [100, 5]
    assert ing.replays == 1
    assert len(ing.rejects) == 1 and "conflicts with a.csv:3" in ing.rejects[0].reason


# ---------------------------------------------------------------- cause 12: same-day plan changes
@pytest.mark.parametrize("rows,expected", [
    ("C1,team,2026-02-14\nC1,starter,2026-02-14\n", "starter"),
    ("C1,starter,2026-02-14\nC1,team,2026-02-14\n", "team"),
    ("C1,business,2026-02-14\nC1,team,2026-02-14\nC1,starter,2026-02-14\n", "starter"),
])
def test_same_day_change_later_row_wins(rows, expected):
    cat = parse_catalog(DOC["datasets"]["mar2026"]["catalog.toml"])
    s = parse_subscriptions("customer,plan,effective\nC1,starter,2026-01-01\n" + rows, catalog=cat)
    assert s.plan_on("C1", date(2026, 2, 20)) == expected
    p = billing_period("2026-02", 1, "UTC")
    assert [seg.plan for seg in s.segments("C1", p)] in (["starter"], ["starter", expected])


# ---------------------------------------------------------------- cause 13: final invoice for closed customers
def test_closed_customer_gets_final_invoice(data_dirs):
    feb = run_billing(data_dirs["mar2026"], "2026-02")
    assert "C13" in [i.customer.id for i in feb.invoices]
    mar = run_of(data_dirs, "mar2026")
    assert "C13" not in [i.customer.id for i in mar.invoices]
    oct_ = run_of(data_dirs, "oct2026")
    assert "C15" in [i.customer.id for i in oct_.invoices]


# ---------------------------------------------------------------- stage 2: rebill
def test_rebill_api(data_dirs):
    from meterbill.rebill import rebill
    adj = rebill(data_dirs["mar2026"])
    assert [(a.issued.customer, a.issued.cycle) for a in adj] == sorted((a.issued.customer, a.issued.cycle) for a in adj)
    by = {a.issued.number: a for a in adj}
    c04 = by["KC-2026-02-C04"]
    assert c04.kind == "debit" and c04.note_number == "DN-KC-2026-02-C04"
    assert c04.change == Money("456.60", "GBP")
    assert c04.deltas()["total"] == Money("0", "GBP") and c04.deltas()["credit"] == Money("-456.60", "GBP")
    c10 = by["KC-2026-02-C10"]
    assert c10.kind == "credit" and c10.note_number == "CN-KC-2026-02-C10"
    assert c10.corrected["total"] - c10.issued.figures["total"] == c10.change
    assert by["KC-2026-02-C01"].kind == "none" and by["KC-2026-02-C01"].note_number == ""
    assert set(adj[0].corrected) == {"subtotal", "discount", "tax", "late_fees", "total", "credit", "due"}


def test_rebill_cycle_filter(data_dirs):
    from meterbill.rebill import rebill
    assert rebill(data_dirs["oct2026"], cycles=["2026-03"]) == []
    assert len(rebill(data_dirs["oct2026"], cycles=["2026-09"])) == 12
    assert len(rebill(data_dirs["oct2026"])) == 24


def test_rebill_cli_matches_api(data_dirs):
    import subprocess
    import sys
    for fmt, name in (("text", "rebill.txt"), ("csv", "rebill.csv")):
        p = subprocess.run([sys.executable, "-m", "meterbill", "rebill", str(data_dirs["oct2026"]), "--format", fmt],
                           cwd=HERE, capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert p.stdout == DOC["goldens"]["oct2026"][name]


def test_rebill_with_unchanged_issued_is_empty(data_dirs, tmp_path):
    import shutil
    from meterbill.rebill import rebill, render_rebill_csv, render_rebill_text
    d = tmp_path / "d"
    shutil.copytree(data_dirs["mar2026"], d)
    for f in (d / "issued").iterdir():
        f.unlink()
    inv = run_billing(d, "2026-02", customers=["C01"]).invoice("C01")
    (d / "issued" / f"{inv.number}.json").write_text(render(inv, "json"))
    adj = rebill(d)
    assert [a.kind for a in adj] == ["none"]
    assert render_rebill_csv(adj) == "note,kind,invoice,customer,cycle,currency,field,issued,corrected,change\n"
    assert render_rebill_text(adj).endswith("  unchanged: KC-2026-02-C01\n")


def test_rebill_text_and_csv_goldens_both_datasets(data_dirs):
    from meterbill.rebill import rebill, render_rebill_csv, render_rebill_text
    for ds in ("mar2026", "oct2026"):
        adj = rebill(data_dirs[ds])
        assert render_rebill_text(adj) == DOC["goldens"][ds]["rebill.txt"]
        assert render_rebill_csv(adj) == DOC["goldens"][ds]["rebill.csv"]


# ---------------------------------------------------------------- chain 14: timestamp parsing is offset-exact
@pytest.mark.parametrize("a,b", [
    ("2026-04-10T00:30:00+02:00", "2026-04-10T00:30:00-05:00"),
    ("2026-10-15T00:20:00+02:00", "2026-10-15T00:20:00-04:00"),
    ("2026-03-01T10:00:00Z", "2026-03-01T10:00:00+01:00"),
])
def test_same_wall_clock_different_offsets_are_different_instants(a, b):
    from meterbill.timeutil import parse_instant
    ia, ib = parse_instant(a), parse_instant(b)
    assert ia != ib
    assert parse_instant(b) == ib and parse_instant(a) == ia


def test_change_day_batch_lands_on_new_plan(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C07")
    team_api = [ln for ln in inv.lines if ln.kind == "usage" and ln.metric == "api_calls" and ln.plan == "team"]
    assert team_api and team_api[0].quantity >= 96000


# ---------------------------------------------------------------- chain 15: allocation weights are exact
def test_allocate_fractional_weights():
    from meterbill.money import allocate
    parts = allocate(Money("1.00", "USD"), [D("0.4"), D("0.6")])
    assert [p.amount for p in parts] == [D("0.40"), D("0.60")]
    parts = allocate(Money("10.00", "USD"), [D("1.5"), D("2.5"), D("0.5")])
    assert [p.amount for p in parts] == [D("3.33"), D("5.56"), D("1.11")]


def test_per_line_tax_with_discount_on_fractional_lines():
    t = TaxTable(parse_tax(DOC["datasets"]["mar2026"]["tax.toml"]))
    lines = [Money("0.40", "USD"), Money("0.60", "USD"), Money("100.00", "USD")]
    r = t.compute(_cust(jurisdiction="US-TX"), lines, Money("10.10", "USD"))
    assert r.tax == Money("5.68", "USD")
    assert [t.amount for t in r.line_taxes] == [D("0.02"), D("0.03"), D("5.63")]


# ---------------------------------------------------------------- chain 16: proration carried unrounded through FX
def test_proration_not_rounded_before_conversion():
    p = billing_period("2026-03", 10, "Asia/Tokyo")
    pr = prorate(D("49.00"), Segment("starter", date(2026, 3, 10), date(2026, 3, 21)), p)
    assert pr.amount == D("17.38709677")


def test_yen_part_month_fees(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C05")
    assert [ln.amount for ln in inv.lines if ln.kind == "base"] == [Money("2626", "JPY"), Money("19393", "JPY")]


# ---------------------------------------------------------------- masking pair 2 (C10)
def test_c10_usage_count_exact(data_dirs):
    inv = run_of(data_dirs, "mar2026").invoice("C10")
    r = run_of(data_dirs, "mar2026")
    recs = [x for x in r.ingested.records if x.customer == "C10" and x.metric == "api_calls" and inv.period.contains(x.at)]
    assert sum(x.quantity for x in recs) == [ln for ln in inv.lines if ln.metric == "api_calls"][0].quantity
    ids = [x.event_id for x in r.ingested.records]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- stage 3: restatement
def _restate(data_dirs, ds):
    from meterbill.restatement import restate
    key = ("restate", ds)
    if key not in _RUNS:
        _RUNS[key] = restate(data_dirs[ds], FIRST[ds], CYCLES[ds])
    return _RUNS[key]


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_restatement_structure(data_dirs, ds):
    res = _restate(data_dirs, ds)
    assert [c.cycle for c in res.cycles] == [FIRST[ds], PREV[ds], CYCLES[ds]]
    for cr in res.cycles:
        assert [i.customer.id for i in cr.invoices] == sorted(i.customer.id for i in cr.invoices)
        for e in cr.journal:
            assert e.balanced(), e.ref
            assert all(p.debit or p.credit for p in e.postings), e.ref
        assert not cr.issued or set(cr.issued) <= {i.number for i in cr.invoices}
    assert res.cycles[-1].issued == {}


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_restatement_last_cycle_matches_rebilled_engine_when_nothing_carries(data_dirs, ds):
    res = _restate(data_dirs, ds)
    first = res.cycles[0]
    plain = run_billing(data_dirs[ds], FIRST[ds])
    for inv in first.invoices:
        assert render(inv, "json") == render(plain.invoice(inv.customer.id), "json"), inv.number


def test_restatement_date(data_dirs):
    assert _restate(data_dirs, "mar2026").on == date(2026, 4, 29)


def test_restatement_credits_created_and_consumed(data_dirs):
    res = _restate(data_dirs, "mar2026")
    created = {g.grant_id: g for cr in res.cycles for g in cr.grants_created}
    assert "RS-KC-2026-01-C01" in created
    g = created["RS-KC-2026-01-C01"]
    assert g.expires == g.granted + timedelta(days=90)
    feb = res.invoice("KC-2026-02-C01")
    assert [u.grant.grant_id for u in feb.credits if u.applied] == ["RS-KC-2026-01-C01"]
    assert all(not gid.startswith("RS-KC-2026-02-C01") for gid in created)


def test_restatement_unpaid_receivable_corrected_not_credited(data_dirs):
    res = _restate(data_dirs, "mar2026")
    feb = res.cycle("2026-02")
    changed = {n for n, _, _ in feb.receivable_changes}
    assert "KC-2026-02-C06" in changed
    assert all(g.grant_id != "RS-KC-2026-02-C06" for g in feb.grants_created)


def test_restatement_journal_reversal_mirrors_issued(data_dirs):
    res = _restate(data_dirs, "mar2026")
    feb = res.cycle("2026-02")
    rev = {e.ref: e for e in feb.journal}
    r, n = rev["REV-KC-2026-02-C04"], rev["KC-2026-02-C04"]
    assert r.postings[0].account == "1200" and r.postings[0].credit and not r.postings[0].debit
    assert n.postings[0].account == "1200" and n.postings[0].debit
    assert [p.account for p in r.postings] == [p.account for p in n.postings]


def test_restatement_revenue_rules(data_dirs):
    res = _restate(data_dirs, "mar2026")
    cr = res.cycle("2026-01")
    inv = [i for i in cr.invoices if i.customer.id == "C01"][0]
    total = sum((v for (c, _), v in cr.revenue.items() if c == "C01"), Money.zero("USD"))
    assert total == inv.subtotal - inv.discount_total - inv.late_fees
    assert cr.revenue[("C01", "2026-01-31")] > cr.revenue[("C01", "2026-01-30")]


def test_restate_cli(data_dirs):
    import subprocess
    import sys
    for rep, name in (("summary", "restate-summary.txt"), ("journal", "restate-journal.csv"),
                      ("revenue", "restate-revenue.csv")):
        p = subprocess.run([sys.executable, "-m", "meterbill", "restate", str(data_dirs["oct2026"]),
                            "2026-08", "2026-10", "--report", rep], cwd=HERE, capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert p.stdout == DOC["goldens"]["oct2026"][name]


def test_restate_empty_window_is_an_error(data_dirs):
    from meterbill.errors import BillingError
    from meterbill.restatement import restate
    with pytest.raises(BillingError):
        restate(data_dirs["mar2026"], "2026-03", "2026-01")


# ---------------------------------------------------------------- stage 4: month-end close
def _close(data_dirs, ds):
    from meterbill.close import close, render_pack
    key = ("close", ds)
    if key not in _RUNS:
        cl = close(data_dirs[ds], FIRST[ds], CYCLES[ds])
        _RUNS[key] = (cl, render_pack(cl))
    return _RUNS[key]


def test_load_entities_and_errors():
    from meterbill.close import load_entities
    from meterbill.errors import ConfigError
    ents = load_entities(DOC["datasets"]["mar2026"]["entities.toml"])
    assert list(ents.entities) == ["KC-EU", "KC-UK", "KC-US"]
    assert ents.entity_for("SEK").code == "KC-EU" and ents.entity_for("JPY").functional_currency == "USD"
    assert ents.presentation_currency == "USD" and ents.parent == "KC-US"
    bad = DOC["datasets"]["mar2026"]["entities.toml"].replace('currencies = ["GBP"]', 'currencies = ["GBP", "EUR"]')
    with pytest.raises(ConfigError):
        load_entities(bad)


def test_close_requires_entities(data_dirs, tmp_path):
    import shutil
    from meterbill.close import close
    from meterbill.errors import ConfigError
    d = tmp_path / "noent"
    shutil.copytree(data_dirs["mar2026"], d)
    (d / "entities.toml").unlink()
    with pytest.raises(ConfigError):
        close(d, "2026-01", "2026-03")


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_close_structure(data_dirs, ds):
    cl, pack = _close(data_dirs, ds)
    assert set(pack) == {"entities.csv", "revaluation.csv", "journal.csv", "trial_balance.csv", "tie_out.csv"}
    assert [m.isoformat()[:7] for m in cl.month_ends] == [FIRST[ds], PREV[ds], CYCLES[ds]]
    for e in cl.entries:
        assert e.balanced(), e.ref
        assert e.entity in ("KC-EU", "KC-UK", "KC-US", "GROUP")
    for me, tb in cl.trial_balance.items():
        assert sum(tb.values(), Money.zero("USD")) == Money.zero("USD")
        for acc in ("1900", "2900", "4800", "4810"):
            assert tb.get(acc, Money.zero("USD")) == Money.zero("USD")
    for r in cl.revaluation:
        assert r.difference == r.closing - r.booked
        assert r.currency != cl.entities.entities[r.entity].functional_currency


@pytest.mark.parametrize("ds", ["mar2026", "oct2026"])
def test_tie_out_api(data_dirs, ds):
    from meterbill.close import tie_out
    cl, pack = _close(data_dirs, ds)
    rows = tie_out(cl)
    assert len(rows) == 5 * len(cl.month_ends)
    assert [r[1] for r in rows[:5]] == ["invoiced_vs_receivable", "revenue_schedule", "cash", "trial_balance", "eliminations"]
    for me, check, exp, act in rows:
        if check != "revenue_schedule":
            assert exp == act, (me, check)


def test_revaluation_reversed_next_day(data_dirs):
    cl, _ = _close(data_dirs, "mar2026")
    refs = {e.ref: e for e in cl.entries}
    fxr = [e for e in cl.entries if e.ref.startswith("FXR-") and not e.ref.endswith("/REV")]
    assert fxr
    for e in fxr:
        rev = refs[e.ref + "/REV"]
        assert rev.date == e.date + timedelta(days=1)
        assert [(p.account, p.debit, p.credit) for p in rev.postings] == [(p.account, p.credit, p.debit) for p in e.postings]


def test_intercompany_charges(data_dirs):
    from meterbill.close import load_entities
    cl, _ = _close(data_dirs, "mar2026")
    ic = [e for e in cl.entries if e.ref.startswith("IC-") and not e.ref.endswith("/S")]
    assert ic
    for e in ic:
        inv = cl.restatement.invoice(e.ref[3:])
        expected = ((inv.subtotal - inv.discount_total - inv.late_fees).amount * D("0.95"))
        assert e.postings[0].debit.amount == expected.quantize(D(1).scaleb(-(2 if inv.currency != "JPY" else 0)), rounding="ROUND_HALF_UP")
    numbers = [e.ref for e in cl.entries if e.ref.startswith("IC-")]
    assert numbers == sorted(numbers, key=lambda r: (r.replace("/S", ""), r.endswith("/S")))
    c14 = [e for e in ic if e.ref.endswith("-C14")]
    assert c14 == []


def test_tie_out_failure_raises(data_dirs, tmp_path):
    from meterbill.close import TieOutError, assert_tied
    cl, _ = _close(data_dirs, "oct2026")
    me = cl.month_ends[0]
    saved = list(cl.tie_rows)
    try:
        cl.tie_rows = [(m, c, e, a + Money("0.01", "USD") if c == "cash" else a) for m, c, e, a in saved]
        with pytest.raises(TieOutError) as ei:
            assert_tied(cl)
        assert f"cash {me.isoformat()}" in str(ei.value)
    finally:
        cl.tie_rows = saved
    assert_tied(cl)


def test_close_cli(data_dirs, tmp_path):
    import subprocess
    import sys
    p = subprocess.run([sys.executable, "-m", "meterbill", "close", str(data_dirs["oct2026"]), "2026-08", "2026-10",
                        "--out", str(tmp_path / "pack")], cwd=HERE, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout == f"wrote 5 file(s) to {tmp_path / 'pack'}\n"
    for name in ("entities.csv", "revaluation.csv", "journal.csv", "trial_balance.csv", "tie_out.csv"):
        assert (tmp_path / "pack" / name).read_text() == DOC["goldens"]["oct2026"]["close-" + name]
    p = subprocess.run([sys.executable, "-m", "meterbill", "close", str(data_dirs["mar2026"]), "2026-01", "2026-03",
                        "--report", "trial_balance"], cwd=HERE, capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout == DOC["goldens"]["mar2026"]["close-trial_balance.csv"]
