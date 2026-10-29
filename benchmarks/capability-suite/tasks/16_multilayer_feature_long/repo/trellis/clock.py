"""Time sources.

All timestamps in trellis are UTC, second resolution, formatted as
``YYYY-MM-DDTHH:MM:SSZ``.  Services take a *clock*: any zero-argument
callable returning such a string.  ``utc_now`` is the real clock; it honours
the ``TRELLIS_NOW`` environment variable so CLI runs can be reproduced.
``FixedClock`` is for tests.

Calendar dates (issue due dates and everything derived from them) are plain
``YYYY-MM-DD`` strings with no time zone; "today" is the date part of the
clock's timestamp.  See ``trellis.dates``.
"""

import os
from datetime import datetime, timedelta, timezone

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_timestamp(text):
    return datetime.strptime(text, FORMAT).replace(tzinfo=timezone.utc)


def format_timestamp(dt):
    return dt.astimezone(timezone.utc).strftime(FORMAT)


def utc_now():
    fixed = os.environ.get("TRELLIS_NOW")
    if fixed:
        parse_timestamp(fixed)  # validate
        return fixed
    return format_timestamp(datetime.now(timezone.utc))


def today_of(clock):
    """The calendar date (``YYYY-MM-DD``) of the clock's current time."""
    return clock()[:10]


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, start="2026-05-01T09:00:00Z"):
        self._now = parse_timestamp(start)

    def __call__(self):
        return format_timestamp(self._now)

    def advance(self, seconds=1):
        self._now += timedelta(seconds=seconds)

    def advance_days(self, days):
        self._now += timedelta(days=days)

    def set(self, timestamp):
        self._now = parse_timestamp(timestamp)
