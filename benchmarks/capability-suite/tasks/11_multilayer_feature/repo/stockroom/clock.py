"""Time source.  Tests and the CLI can pin "now" with STOCKROOM_NOW."""

import datetime as _dt
import os


def utc_now():
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``.

    If the STOCKROOM_NOW environment variable is set, its value is returned
    verbatim, which keeps CLI output reproducible.
    """
    pinned = os.environ.get("STOCKROOM_NOW")
    if pinned:
        return pinned
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


class FixedClock:
    """A clock for tests: returns ``start`` and can be advanced by seconds."""

    def __init__(self, start="2026-01-01T00:00:00Z"):
        self._t = _dt.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")

    def __call__(self):
        return self._t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def advance(self, seconds=1):
        self._t += _dt.timedelta(seconds=seconds)
