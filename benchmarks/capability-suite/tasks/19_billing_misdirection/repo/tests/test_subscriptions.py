from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from meterbill.errors import ConfigError, UnknownPlan
from meterbill.periods import billing_period
from meterbill.proration import fraction_of, prorate, prorate_all
from meterbill.subscriptions import Segment, parse_subscriptions

from .helpers import catalog

D = Decimal
HEAD = "customer,plan,effective\n"


def subs(rows):
    return parse_subscriptions(HEAD + rows, catalog=catalog())


def test_plan_on_and_none():
    s = subs("C1,team,2026-01-01\nC1,none,2026-03-10\nC1,starter,2026-04-01\n")
    assert s.plan_on("C1", date(2025, 12, 31)) is None
    assert s.plan_on("C1", date(2026, 2, 1)) == "team"
    assert s.plan_on("C1", date(2026, 3, 10)) is None
    assert s.plan_on("C1", date(2026, 4, 1)) == "starter"


def test_segments_cut_at_changes():
    s = subs("C1,starter,2026-01-01\nC1,team,2026-03-12\n")
    p = billing_period("2026-03", 1, "UTC")
    segs = s.segments("C1", p)
    assert segs == [Segment("starter", date(2026, 3, 1), date(2026, 3, 12)),
                    Segment("team", date(2026, 3, 12), date(2026, 4, 1))]
    assert [x.days for x in segs] == [11, 20]


def test_segments_merge_repeated_plan_and_skip_gaps():
    s = subs("C1,team,2026-03-05\nC1,team,2026-03-20\n")
    p = billing_period("2026-03", 1, "UTC")
    assert s.segments("C1", p) == [Segment("team", date(2026, 3, 5), date(2026, 4, 1))]


def test_rows_in_any_order():
    s = subs("C1,team,2026-03-12\nC1,starter,2026-01-01\n")
    assert s.plan_on("C1", date(2026, 3, 1)) == "starter"


def test_legacy_switch_and_unknown_plan_rejected():
    with pytest.raises(ConfigError):
        subs("C1,team,2026-01-01\nC1,legacy_basic,2026-03-01\n")
    with pytest.raises(UnknownPlan):
        subs("C1,gold,2026-01-01\n")


def test_proration_calendar_month_period():
    p = billing_period("2026-03", 1, "UTC")
    seg = Segment("team", date(2026, 3, 12), date(2026, 4, 1))
    pr = prorate(D("199.00"), seg, p)
    assert (pr.days, pr.period_days, pr.fraction) == (20, 31, Fraction(20, 31))
    assert pr.amount == D("128.38709677")
    assert not pr.full


def test_proration_full_period():
    p = billing_period("2026-02", 1, "UTC")
    pr = prorate(D("49.00"), Segment("starter", date(2026, 2, 1), date(2026, 3, 1)), p)
    assert pr.full and pr.amount == D("49.00000000")


def test_prorate_all():
    s = subs("C1,starter,2026-01-01\nC1,team,2026-03-12\n")
    p = billing_period("2026-03", 1, "UTC")
    prs = prorate_all(catalog(), s.segments("C1", p), p)
    assert sum(x.amount for x in prs) == D("17.38709677") + D("128.38709677")


def test_fraction_of_bounds():
    with pytest.raises(ValueError):
        fraction_of(32, 31)
    with pytest.raises(ValueError):
        fraction_of(1, 0)
