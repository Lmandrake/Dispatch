from datetime import date, datetime, timezone

import pytest

from meterbill.errors import PeriodError
from meterbill.periods import (anchored_day, billing_period, cycles_between, next_cycle, parse_cycle,
                               period_for_day, prev_cycle)

UTC = timezone.utc


def test_cycle_helpers():
    assert parse_cycle("2026-03") == (2026, 3)
    assert next_cycle("2026-12") == "2027-01"
    assert prev_cycle("2026-01") == "2025-12"
    assert cycles_between("2025-11", "2026-02") == 3
    for bad in ("2026-13", "26-03", "2026/03"):
        with pytest.raises(PeriodError):
            parse_cycle(bad)


def test_anchor_clamps_to_month_end():
    assert anchored_day(2026, 2, 31) == date(2026, 2, 28)
    assert anchored_day(2028, 2, 30) == date(2028, 2, 29)
    with pytest.raises(PeriodError):
        anchored_day(2026, 1, 0)


def test_period_anchor_one_utc():
    p = billing_period("2026-02", 1, "UTC")
    assert (p.start, p.end, p.days) == (date(2026, 2, 1), date(2026, 3, 1), 28)
    assert p.start_utc == datetime(2026, 2, 1, tzinfo=UTC)
    assert p.end_utc == datetime(2026, 3, 1, tzinfo=UTC)
    assert p.label() == "2026-02-01 to 2026-02-28"


def test_period_anchor_fifteen_tokyo():
    p = billing_period("2026-03", 15, "Asia/Tokyo")
    assert (p.start, p.last_day, p.days) == (date(2026, 3, 15), date(2026, 4, 14), 31)
    assert p.start_utc == datetime(2026, 3, 14, 15, 0, tzinfo=UTC)
    assert p.end_utc == datetime(2026, 4, 14, 15, 0, tzinfo=UTC)
    assert p.hours() == 31 * 24


def test_period_contains_is_half_open():
    p = billing_period("2026-01", 1, "Asia/Tokyo")
    assert p.contains(p.start_utc)
    assert not p.contains(p.end_utc)


def test_period_in_winter_new_york():
    p = billing_period("2026-01", 1, "America/New_York")
    assert p.start_utc == datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    assert p.end_utc == datetime(2026, 2, 1, 5, 0, tzinfo=UTC)


def test_period_for_day():
    assert period_for_day(date(2026, 4, 3), 15, "UTC").cycle == "2026-03"
    assert period_for_day(date(2026, 4, 15), 15, "UTC").cycle == "2026-04"
