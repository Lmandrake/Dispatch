"""Calendar-date helpers.

Due dates are calendar dates written ``YYYY-MM-DD``.  They have no time of
day and no time zone, so daylight-saving changes never affect them: adding
one day always moves to the next calendar date.  All arithmetic here works
on ``datetime.date`` and is exact.

Relative dates (accepted by the CLI and the query language)::

    today  tomorrow  yesterday
    +3d  -2d         days from today
    +2w  -1w         weeks (7 days) from today
    +1m  -6m         calendar months from today (see add_months)
"""

import calendar
import re
from datetime import date, timedelta

from trellis.errors import ValidationError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RELATIVE = re.compile(r"^([+-])(\d{1,4})([dwm])$")


def parse_date(text):
    """Parse a strict ``YYYY-MM-DD`` string into a ``date``."""
    if not isinstance(text, str):
        raise ValidationError(f"not a date: {text!r}")
    m = _ISO.match(text.strip())
    if not m:
        raise ValidationError(f"not a date (want YYYY-MM-DD): {text!r}")
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        raise ValidationError(f"no such date: {text!r}") from None


def format_date(d):
    return d.isoformat()


def is_date(text):
    try:
        parse_date(text)
    except ValidationError:
        return False
    return True


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def add_days(d, n):
    return d + timedelta(days=n)


def add_months(d, n):
    """``d`` moved by ``n`` calendar months.  When the target month is too
    short for ``d.day`` the result is clamped to that month's last day, so
    ``add_months(2026-01-31, 1)`` is 2026-02-28.  Note that clamping is lossy:
    ``add_months(add_months(2026-01-31, 1), 1)`` is 2026-03-28, not 03-31."""
    index = d.year * 12 + (d.month - 1) + n
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, days_in_month(year, month)))


def months_between(a, b):
    """Whole calendar-month index difference ``b - a`` (days ignored)."""
    return (b.year * 12 + b.month) - (a.year * 12 + a.month)


def week_start(d):
    """The Monday on or before ``d``."""
    return d - timedelta(days=d.weekday())


def weekday_name(d):
    return WEEKDAYS[d.weekday()]


def weekday_index(name):
    key = name.strip().lower()
    if key not in WEEKDAYS:
        raise ValidationError(f"unknown weekday {name!r}; use one of {', '.join(WEEKDAYS)}")
    return WEEKDAYS.index(key)


def resolve_date(text, today):
    """Turn user text into a ``YYYY-MM-DD`` string.  ``today`` is a
    ``YYYY-MM-DD`` string (the clock's date).  Accepts ISO dates and the
    relative forms listed in the module docstring."""
    raw = text.strip().lower()
    base = parse_date(today)
    if raw == "today":
        return format_date(base)
    if raw == "tomorrow":
        return format_date(add_days(base, 1))
    if raw == "yesterday":
        return format_date(add_days(base, -1))
    m = _RELATIVE.match(raw)
    if m:
        n = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        unit = m.group(3)
        if unit == "d":
            return format_date(add_days(base, n))
        if unit == "w":
            return format_date(add_days(base, 7 * n))
        return format_date(add_months(base, n))
    return format_date(parse_date(text))


def days_until(due, today):
    """Signed number of days from ``today`` to ``due`` (both strings)."""
    return (parse_date(due) - parse_date(today)).days


def iso_week(d):
    """``YYYY-Www`` label of the ISO week containing ``d``."""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"
