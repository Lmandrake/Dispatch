"""Displaying timestamps in a fixed UTC offset.

Archives always store UTC microseconds.  For display, the CLI accepts
``--tz +02:00`` (or ``-05:30``, ``Z``, ``UTC``) and shows local times as
``2026-03-01T14:00:00+02:00``.  Only fixed offsets are supported; there is no
daylight-saving logic on purpose.
"""
import re

from .errors import SchemaError
from .timeutil import US_PER_SECOND, format_ts

_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def parse_offset(text):
    """Offset in microseconds east of UTC."""
    t = text.strip().upper()
    if t in ("Z", "UTC", "GMT", "+00:00", "-00:00"):
        return 0
    m = _OFFSET.match(t)
    if not m:
        raise SchemaError(f"bad UTC offset {text!r} (expected +HH:MM or -HH:MM)")
    sign, hh, mm = m.groups()
    hours, minutes = int(hh), int(mm)
    if hours > 14 or minutes > 59:
        raise SchemaError(f"UTC offset out of range: {text!r}")
    us = (hours * 3600 + minutes * 60) * US_PER_SECOND
    return us if sign == "+" else -us


def format_offset(us):
    if us == 0:
        return "Z"
    sign = "+" if us > 0 else "-"
    minutes = abs(us) // (60 * US_PER_SECOND)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def format_local(us, offset):
    """``format_ts`` of the shifted time, with the offset instead of ``Z``."""
    text = format_ts(us + offset)
    if text.startswith("@"):
        return text
    return text[:-1] + format_offset(offset)
