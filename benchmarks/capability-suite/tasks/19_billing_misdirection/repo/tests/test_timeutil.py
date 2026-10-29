from datetime import date, datetime, timedelta, timezone

import pytest

from meterbill.errors import ConfigError
from meterbill.timeutil import format_instant, local_date, local_midnight, parse_instant, zone

UTC = timezone.utc


@pytest.mark.parametrize("text,expected", [
    ("2026-03-04T10:15:00Z", datetime(2026, 3, 4, 10, 15, tzinfo=UTC)),
    ("2026-03-04T11:15:00+01:00", datetime(2026, 3, 4, 10, 15, tzinfo=UTC)),
    ("2026-03-04T05:15-0500", datetime(2026, 3, 4, 10, 15, tzinfo=UTC)),
    ("2026-03-04 10:15:00.250Z", datetime(2026, 3, 4, 10, 15, 0, 250000, tzinfo=UTC)),
    ("1772619300", datetime(2026, 3, 4, 10, 15, tzinfo=UTC)),
    ("1772619300250", datetime(2026, 3, 4, 10, 15, 0, 250000, tzinfo=UTC)),
    ("1772619300.5", datetime(2026, 3, 4, 10, 15, 0, 500000, tzinfo=UTC)),
])
def test_parse_instant_forms(text, expected):
    assert parse_instant(text) == expected


@pytest.mark.parametrize("bad", ["2026-03-04T10:15:00", "2026-03-04", "yesterday", "", "2026-03-04T10:15:00+25:00"])
def test_parse_instant_rejects(bad):
    with pytest.raises(ValueError):
        parse_instant(bad)


def test_format_instant_roundtrip():
    t = parse_instant("2026-03-04T11:15:07+01:00")
    assert format_instant(t) == "2026-03-04T10:15:07Z"
    assert parse_instant(format_instant(t)) == t


def test_local_midnight_and_date():
    assert local_midnight(date(2026, 3, 1), "Asia/Tokyo") == datetime(2026, 2, 28, 15, 0, tzinfo=UTC)
    assert local_midnight(date(2026, 1, 1), "America/New_York") == datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    assert local_date(datetime(2026, 2, 28, 15, 30, tzinfo=UTC), "Asia/Tokyo") == date(2026, 3, 1)


def test_local_midnight_skipped_by_dst():
    # America/Santiago springs forward at 00:00 -> 01:00 on 2026-09-06
    m = local_midnight(date(2026, 9, 6), "America/Santiago")
    assert m.astimezone(zone("America/Santiago")).hour == 1


def test_zone_unknown():
    with pytest.raises(ConfigError):
        zone("Mars/Olympus_Mons")
    assert zone("UTC").utcoffset(None) == timedelta(0)
