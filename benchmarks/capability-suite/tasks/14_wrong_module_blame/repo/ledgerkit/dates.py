"""Date parsing and reporting periods."""

from datetime import date, datetime

from .errors import DateError
from .locales import get_locale

PERIOD_KINDS = ("month", "quarter", "year")


def parse_date(text, locale=None, *, line=None, source=None):
    """Parse ``text`` with the locale's date formats (ISO is always accepted)."""
    spec = get_locale(locale)
    s = text.strip()
    for fmt in spec.date_formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise DateError(f"bad date {text!r} for locale {spec.name}", line=line, source=source)


def parse_iso(text, *, line=None, source=None):
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise DateError(f"bad ISO date {text!r}", line=line, source=source) from None


def period_of(day, kind="month"):
    """Return the period label for ``day``: ``2026-03``, ``2026-Q1`` or ``2026``."""
    if kind == "month":
        return f"{day.year:04d}-{day.month:02d}"
    if kind == "quarter":
        return f"{day.year:04d}-Q{(day.month - 1) // 3 + 1}"
    if kind == "year":
        return f"{day.year:04d}"
    raise ValueError(f"unknown period kind {kind!r}")


def period_start(label):
    """First day of the period named by ``label`` (inverse of period_of)."""
    if len(label) == 4:
        return date(int(label), 1, 1)
    year, rest = label.split("-")
    if rest.startswith("Q"):
        q = int(rest[1:])
        return date(int(year), 3 * (q - 1) + 1, 1)
    return date(int(year), int(rest), 1)


def sort_periods(labels):
    return sorted(set(labels), key=period_start)
