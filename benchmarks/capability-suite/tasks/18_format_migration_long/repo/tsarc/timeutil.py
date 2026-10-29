"""Timestamps (microseconds since the Unix epoch) and durations.

All arithmetic is done on integers; nothing goes through float seconds, so
every i64 microsecond value formats and parses back exactly.
"""
import datetime as _dt
import re

from .errors import SchemaError

US_PER_SECOND = 1_000_000
_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?"
    r"(Z|[+-]\d{2}:\d{2})?$"
)
_DURATION = re.compile(r"(\d+)(us|ms|s|m|h|d|w)")
_UNIT_US = {
    "us": 1,
    "ms": 1_000,
    "s": US_PER_SECOND,
    "m": 60 * US_PER_SECOND,
    "h": 3600 * US_PER_SECOND,
    "d": 86400 * US_PER_SECOND,
    "w": 7 * 86400 * US_PER_SECOND,
}


def format_ts(us):
    """``YYYY-MM-DDTHH:MM:SSZ``, or ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` when there is a fraction.

    Values outside the years 1..9999 are written as ``@<microseconds>``.
    """
    seconds, frac = divmod(us, US_PER_SECOND)
    days, rem = divmod(seconds, 86400)
    try:
        moment = _EPOCH + _dt.timedelta(days=days, seconds=rem)
    except OverflowError:
        return f"@{us}"
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    if moment.year < 1000:
        text = f"{moment.year:04d}" + text[text.index("-"):]
    if frac:
        text += f".{frac:06d}"
    return text + "Z"


def parse_ts(text):
    """Parse a timestamp; returns microseconds.

    Accepted forms: ISO-8601 dates and date-times (``2026-03-01``,
    ``2026-03-01T12:00``, ``2026-03-01T12:00:05.25Z``, an optional ``Z`` or
    ``+HH:MM`` offset), ``@<int>`` for raw microseconds, and a bare integer
    meaning epoch **seconds**.
    """
    t = text.strip()
    if not t:
        raise SchemaError("empty timestamp")
    if t.startswith("@"):
        try:
            return int(t[1:], 10)
        except ValueError:
            raise SchemaError(f"bad timestamp: {text!r}") from None
    if re.fullmatch(r"[+-]?\d+", t):
        return int(t, 10) * US_PER_SECOND
    m = _ISO.match(t)
    if not m:
        raise SchemaError(f"bad timestamp: {text!r}")
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    try:
        moment = _dt.datetime(int(year), int(month), int(day), int(hh or 0), int(mm or 0),
                              int(ss or 0), tzinfo=_dt.timezone.utc)
    except ValueError as exc:
        raise SchemaError(f"bad timestamp: {text!r} ({exc})") from None
    delta = moment - _EPOCH
    us = (delta.days * 86400 + delta.seconds) * US_PER_SECOND
    if frac:
        us += int(frac.ljust(6, "0"))
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        offset = (int(tz[1:3]) * 3600 + int(tz[4:6]) * 60) * US_PER_SECOND
        us -= sign * offset
    return us


def parse_duration(text):
    """Parse ``90s``, ``5m``, ``1h30m``, ``250ms``, ``2d`` ... into microseconds (> 0)."""
    t = text.strip().lower()
    if not t:
        raise SchemaError("empty duration")
    pos = 0
    total = 0
    for m in _DURATION.finditer(t):
        if m.start() != pos:
            raise SchemaError(f"bad duration: {text!r}")
        total += int(m.group(1)) * _UNIT_US[m.group(2)]
        pos = m.end()
    if pos != len(t):
        raise SchemaError(f"bad duration: {text!r}")
    if total <= 0:
        raise SchemaError(f"duration must be positive: {text!r}")
    return total


def format_duration(us):
    """Inverse of :func:`parse_duration` for positive values, largest units first."""
    if us <= 0:
        raise ValueError("duration must be positive")
    parts = []
    for unit in ("w", "d", "h", "m", "s", "ms", "us"):
        size = _UNIT_US[unit]
        if us >= size:
            n, us = divmod(us, size)
            parts.append(f"{n}{unit}")
    return "".join(parts)


def now_us():
    delta = _dt.datetime.now(_dt.timezone.utc) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * US_PER_SECOND + delta.microseconds


def floor_to(us, every, origin=0):
    """Start of the ``every``-wide bucket containing ``us`` (buckets aligned to ``origin``)."""
    return origin + ((us - origin) // every) * every
