from datetime import date

import pytest

from trellis.dates import (
    add_months,
    days_until,
    iso_week,
    parse_date,
    resolve_date,
    week_start,
    weekday_index,
)
from trellis.errors import ValidationError


def test_parse_date_strict():
    assert parse_date("2026-02-28") == date(2026, 2, 28)
    for bad in ("2026-2-28", "2026-02-30", "28/02/2026", "", "2026-02-28T00:00:00Z"):
        with pytest.raises(ValidationError):
            parse_date(bad)


def test_add_months_clamps():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    # clamping is lossy when chained
    assert add_months(add_months(date(2026, 1, 31), 1), 1) == date(2026, 3, 28)


def test_relative_dates():
    assert resolve_date("today", "2026-05-01") == "2026-05-01"
    assert resolve_date("tomorrow", "2026-05-01") == "2026-05-02"
    assert resolve_date("+3d", "2026-05-01") == "2026-05-04"
    assert resolve_date("-1w", "2026-05-01") == "2026-04-24"
    assert resolve_date("+1m", "2026-01-31") == "2026-02-28"
    assert resolve_date("2026-12-24", "2026-05-01") == "2026-12-24"


def test_no_dst_effects():
    # 2026-03-08 and 2026-11-01 are US DST switch days; dates do not care
    assert resolve_date("+1d", "2026-03-08") == "2026-03-09"
    assert resolve_date("+1d", "2026-11-01") == "2026-11-02"


def test_week_helpers():
    assert week_start(date(2026, 5, 3)) == date(2026, 4, 27)  # Sunday -> Monday before
    assert week_start(date(2026, 5, 4)) == date(2026, 5, 4)
    assert weekday_index("Thu") == 3
    assert iso_week(date(2026, 1, 1)) == "2026-W01"
    assert days_until("2026-05-04", "2026-05-01") == 3
