"""A small cron-expression parser (five fields, UTC).

    ┌ minute        0-59
    │ ┌ hour        0-23
    │ │ ┌ day       1-31
    │ │ │ ┌ month   1-12 or jan-dec
    │ │ │ │ ┌ dow   0-6 or sun-sat (7 is also Sunday)
    * * * * *

Each field accepts ``*``, a number, a range ``a-b``, a list ``a,b,c`` and a
step ``*/n`` or ``a-b/n``. Like classic cron, when both day-of-month and
day-of-week are restricted (neither is ``*``), a time matches if EITHER
matches. Aliases: ``@hourly``, ``@daily`` (``@midnight``), ``@weekly``,
``@monthly``, ``@yearly`` (``@annually``).

Times are seconds since the epoch, interpreted in UTC. ``next_after(t)``
returns the first matching minute strictly after ``t``.
"""

import calendar
import time
from dataclasses import dataclass
from typing import FrozenSet, List, Optional

from .errors import CronError

ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}

MONTHS = {name: i for i, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
DAYS = {name: i for i, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}

FIELDS = (
    ("minute", 0, 59, None),
    ("hour", 0, 23, None),
    ("day", 1, 31, None),
    ("month", 1, 12, MONTHS),
    ("dow", 0, 7, DAYS),
)

# give up searching after this many years without a match (e.g. "0 0 30 2 *")
SEARCH_YEARS = 5

def _month_days(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 else 28
    return 31 - (month - 1) % 7 % 2


def _weekday(year: int, month: int, day: int) -> int:
    """0=Sunday .. 6=Saturday (Sakamoto)."""
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if month < 3:
        year -= 1
    return (year + year // 4 - year // 100 + year // 400 + t[month - 1] + day) % 7


def _value(text: str, lo: int, hi: int, names, field: str) -> int:
    t = text.lower()
    if names and t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f"{field}: {text!r} is not a number")
    v = int(t)
    if not lo <= v <= hi:
        raise CronError(f"{field}: {v} is outside {lo}-{hi}")
    return v


def _parse_field(text: str, lo: int, hi: int, names, field: str) -> FrozenSet[int]:
    out = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{field}: empty list element")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{field}: bad step {step_text!r}")
            step = int(step_text)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a_text, b_text = part.split("-", 1)
            a = _value(a_text, lo, hi, names, field)
            b = _value(b_text, lo, hi, names, field)
            if a > b:
                raise CronError(f"{field}: range {a}-{b} runs backwards")
        else:
            a = _value(part, lo, hi, names, field)
            b = hi if step > 1 else a
        out.update(range(a, b + 1, step))
    return frozenset(out)


@dataclass(frozen=True)
class CronExpr:
    text: str
    minutes: FrozenSet[int]
    hours: FrozenSet[int]
    days: FrozenSet[int]
    months: FrozenSet[int]
    dows: FrozenSet[int]
    day_any: bool
    dow_any: bool

    def matches(self, t: float) -> bool:
        tm = time.gmtime(t)
        if tm.tm_min not in self.minutes or tm.tm_hour not in self.hours or tm.tm_mon not in self.months:
            return False
        return self._day_ok(tm.tm_year, tm.tm_mon, tm.tm_mday)

    def _day_ok(self, year: int, month: int, day: int) -> bool:
        dow = _weekday(year, month, day)
        day_hit = day in self.days
        dow_hit = dow in self.dows
        if self.day_any and self.dow_any:
            return True
        if self.day_any:
            return dow_hit
        if self.dow_any:
            return day_hit
        return day_hit or dow_hit

    def next_after(self, t: float) -> float:
        """The first matching minute strictly after ``t`` (UTC)."""
        start = int(t // 60 + 1) * 60
        tm = time.gmtime(start)
        year, month, day, hour, minute = tm.tm_year, tm.tm_mon, tm.tm_mday, tm.tm_hour, tm.tm_min
        limit_year = year + SEARCH_YEARS
        while year <= limit_year:
            if month not in self.months:
                month, day, hour, minute = month + 1, 1, 0, 0
                if month > 12:
                    year, month = year + 1, 1
                continue
            if day > _month_days(year, month):
                month, day, hour, minute = month + 1, 1, 0, 0
                if month > 12:
                    year, month = year + 1, 1
                continue
            if not self._day_ok(year, month, day):
                day, hour, minute = day + 1, 0, 0
                continue
            if hour not in self.hours:
                hour, minute = hour + 1, 0
                if hour > 23:
                    day, hour = day + 1, 0
                continue
            if minute not in self.minutes:
                minute += 1
                if minute > 59:
                    hour, minute = hour + 1, 0
                    if hour > 23:
                        day, hour = day + 1, 0
                continue
            return float(calendar.timegm((year, month, day, hour, minute, 0)))
        raise CronError(f"{self.text!r} has no match within {SEARCH_YEARS} years")

    def upcoming(self, t: float, n: int) -> List[float]:
        out = []
        for _ in range(n):
            t = self.next_after(t)
            out.append(t)
        return out


def parse_cron(text: str) -> CronExpr:
    if not isinstance(text, str) or not text.strip():
        raise CronError("empty cron expression")
    src = text.strip()
    expanded = ALIASES.get(src.lower(), src)
    parts = expanded.split()
    if len(parts) != 5:
        raise CronError(f"{src!r}: expected 5 fields, got {len(parts)}")
    sets = []
    for part, (field, lo, hi, names) in zip(parts, FIELDS):
        sets.append(_parse_field(part, lo, hi, names, field))
    dows = frozenset(7 % 7 if d == 7 else d for d in sets[4])
    return CronExpr(src, sets[0], sets[1], sets[2], sets[3], dows,
                    day_any=parts[2] == "*", dow_any=parts[4] == "*")


def format_slot(t: float) -> str:
    """``YYYY-MM-DDTHH:MM`` (UTC) for a schedule slot."""
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(t))
