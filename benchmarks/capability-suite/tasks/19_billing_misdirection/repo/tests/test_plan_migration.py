"""Plan migration recommendations."""

import pytest

from meterbill.errors import UnknownPlan
from meterbill.money import Money
from meterbill.plan_migration import eligible_plans, recommend, render_advice

from .helpers import D, catalog, converter, customer
from datetime import date

ON = date(2026, 3, 31)
CAT = catalog()
CONV = converter()


def advice(plan, usage, **cust):
    return recommend(CAT, customer(**cust), plan, usage, CONV, ON)


def test_eligible_plans_by_currency_and_legacy():
    assert eligible_plans(CAT, "USD") == ["business", "starter", "team"]
    assert eligible_plans(CAT, "EUR") == ["business_eu", "team_eu"]
    assert eligible_plans(CAT, "JPY") == []


def test_heavy_user_on_starter_should_move():
    a = advice("starter", {"api_calls": 4_800_000, "storage_gb": "400", "seats": 5})
    assert a.should_switch and a.recommended.plan == "team"
    assert a.savings == a.current.total - a.recommended.total and a.savings > Money.zero("USD")
    assert [q.total.amount for q in a.alternatives] == sorted(q.total.amount for q in a.alternatives)


def test_light_user_stays_on_starter():
    a = advice("starter", {"api_calls": 1000, "storage_gb": 1, "seats": 1})
    assert not a.should_switch and a.savings == Money.zero("USD") and a.savings_percent == "0.0"
    assert "stay on the current plan" in render_advice(a)


def test_legacy_baseline_is_quoted_but_never_recommended():
    a = advice("legacy_basic", {"api_calls": 10000})
    assert a.current.plan == "legacy_basic"
    assert "legacy_basic" not in [q.plan for q in a.alternatives]
    assert not a.should_switch  # 35.00 beats starter's 49.00: stay, do not "move"
    big = advice("legacy_basic", {"api_calls": 5_000_000})
    assert big.should_switch and big.recommended.plan != "legacy_basic"


def test_currency_family_only():
    a = advice("team_eu", {"api_calls": 100}, currency="EUR")
    assert {q.plan for q in a.alternatives} == {"team_eu", "business_eu"}
    assert a.current.currency == "EUR"


def test_no_eligible_plans_means_stay():
    a = advice("starter", {"api_calls": 100}, currency="JPY")
    assert not a.should_switch and a.alternatives == ()
    assert "No non-legacy plans are priced in JPY" in render_advice(a)


def test_tie_prefers_current():
    # identical totals: current plan is kept even if another plan sorts first
    a = advice("business", {})
    b = advice("starter", {})
    assert b.recommended.plan == "starter" and a.recommended.plan == "starter" and a.should_switch


def test_savings_percent():
    a = advice("business", {"api_calls": 1000})
    assert a.should_switch
    pct = D(a.savings_percent)
    assert D("0") < pct < D("100")


def test_unknown_plan():
    with pytest.raises(UnknownPlan):
        advice("platinum", {})


def test_render_lists_alternatives_and_marks_current():
    a = advice("starter", {"api_calls": 5_000_000})
    text = render_advice(a)
    assert "Saving per cycle:" in text and "<- current" in text
    assert text.index("Recommended plan:") < text.index("Eligible plans")
    assert render_advice(a) == text
