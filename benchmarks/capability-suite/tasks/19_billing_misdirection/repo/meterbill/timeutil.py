"""Timestamp parsing and timezone helpers.

Metering timestamps are instants.  The feeds spell them several ways:

* ISO 8601 with ``Z`` or a numeric offset: ``2026-03-04T10:15:00Z``,
  ``2026-03-04T11:15:00+01:00``;
* ISO 8601 with fractional seconds: ``2026-03-04T10:15:00.250Z``;
* Unix epoch seconds (integer or with a fraction): ``1772619300``;
* Unix epoch milliseconds, recognised by having 13 digits.

A timestamp without an offset is refused: we never guess a zone for usage.
Every instant is returned as an aware ``datetime`` in UTC.
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError

UTC = timezone.utc

_ISO = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[T ](?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:\.(?P<frac>\d{1,6}))?)?"
    r"(?P<tz>Z|z|[+-]\d{2}:?\d{2})$"
)
_EPOCH = re.compile(r"^\d{9,13}(?:\.\d{1,6})?$")

_ZONES = {}
_INSTANTS = {}


def zone(name):
    """Return a ZoneInfo for an IANA name, cached; ConfigError if unknown."""
    if name in _ZONES:
        return _ZONES[name]
    if name in ("UTC", "Etc/UTC", "Z"):
        z = UTC
    else:
        try:
            z = ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError(f"unknown timezone {name!r}") from None
    _ZONES[name] = z
    return z


def _offset(text):
    if text in ("Z", "z"):
        return UTC
    sign = 1 if text[0] == "+" else -1
    digits = text[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:])
    if hours > 23 or minutes > 59:
        raise ValueError(f"bad UTC offset {text!r}")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_instant(text):
    """Parse a metering timestamp to an aware UTC datetime.

    Raises ValueError for anything that is not one of the documented forms.
    """
    if isinstance(text, (int,)) and not isinstance(text, bool):
        text = str(text)
    if not isinstance(text, str):
        raise ValueError(f"not a timestamp: {text!r}")
    s = text.strip()
    if _EPOCH.match(s):
        whole, _, frac = s.partition(".")
        if len(whole) == 13:
            if frac:
                raise ValueError(f"fractional epoch milliseconds: {text!r}")
            seconds = int(whole) // 1000
            micros = (int(whole) % 1000) * 1000
        else:
            seconds = int(whole)
            micros = int(frac.ljust(6, "0")) if frac else 0
        return datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=micros)
    m = _ISO.match(s)
    if not m:
        raise ValueError(f"not a timestamp with an offset: {text!r}")
    key = s[:19]
    hit = _INSTANTS.get(key)
    if hit is not None:
        return hit
    frac = m.group("frac") or ""
    local = datetime(
        int(m.group("y")), int(m.group("mo")), int(m.group("d")),
        int(m.group("h")), int(m.group("mi")), int(m.group("s") or 0),
        int(frac.ljust(6, "0")) if frac else 0,
    )
    instant = local.replace(tzinfo=_offset(m.group("tz"))).astimezone(UTC)
    _INSTANTS[key] = instant
    return instant


def format_instant(dt):
    """ISO 8601 UTC with a ``Z`` suffix and whole seconds (micros if present)."""
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def local_midnight(day, tz):
    """The UTC instant at which local calendar ``day`` begins in zone ``tz``.

    Midnight that does not exist (a zone that springs forward at 00:00) maps
    to the first instant of the day that does.
    """
    z = zone(tz) if isinstance(tz, str) else tz
    naive = datetime.combine(day, time())
    aware = naive.replace(tzinfo=z)
    # A non-existent local time round-trips to a different wall clock.
    back = aware.astimezone(UTC).astimezone(z)
    if back.replace(tzinfo=None) != naive:
        aware = (naive + timedelta(hours=1)).replace(tzinfo=z)
    return aware.astimezone(UTC)


def local_date(instant, tz):
    """The calendar date of a UTC instant as seen in zone ``tz``."""
    z = zone(tz) if isinstance(tz, str) else tz
    return instant.astimezone(z).date()


def parse_date(text):
    """Parse ``YYYY-MM-DD``; ValueError otherwise."""
    if isinstance(text, date) and not isinstance(text, datetime):
        return text
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}") from None


def days_between(a, b):
    """Whole days from date ``a`` to date ``b`` (b - a)."""
    return (b - a).days
