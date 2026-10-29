"""Exchange-rate tables.

A rates file has one rate per line::

    2026-01-01  EUR  1.0850      ; optional comment
    2026-03-16  EUR  1.0822

meaning: from the effective date onward (inclusive), one EUR is worth 1.0850
units of the base currency, until the next line for EUR takes effect.  Lines
may appear in any order.  Values are "C" decimals whatever the ledger locale.
A ``base XXX`` line names the base currency (default USD).  The base currency
always has rate 1.

A rate is in effect from its effective day, so two postings on different days
of the same month can use different rates.
"""

import bisect
from datetime import date
from decimal import Decimal

from .dates import parse_iso
from .errors import ParseError, RateNotFound
from .models import Rate
from .amounts import parse_c_decimal

DEFAULT_BASE = "USD"


class RateTable:
    def __init__(self, base=DEFAULT_BASE):
        self.base = base.upper()
        self._by_currency = {}       # currency -> sorted list of Rate

    def add(self, currency, effective, value, *, line=None, source=None):
        currency = currency.upper()
        if currency == self.base:
            raise ParseError(f"rate given for the base currency {currency}",
                             line=line, source=source)
        if value <= 0:
            raise ParseError(f"rate for {currency} must be positive", line=line, source=source)
        rates = self._by_currency.setdefault(currency, [])
        days = [r.effective for r in rates]
        i = bisect.bisect_left(days, effective)
        if i < len(rates) and rates[i].effective == effective:
            if rates[i].value != value:
                raise ParseError(f"conflicting {currency} rates on {effective}",
                                 line=line, source=source)
            return rates[i]
        rate = Rate(currency, effective, Decimal(value))
        rates.insert(i, rate)
        return rate

    def currencies(self):
        return sorted(self._by_currency)

    def history(self, currency):
        return list(self._by_currency.get(currency.upper(), []))

    def rate_on(self, currency, day):
        """The Rate in effect for ``currency`` on ``day``."""
        currency = currency.upper()
        if currency == self.base:
            return Rate(currency, date.min, Decimal(1))
        rates = self._by_currency.get(currency)
        if not rates:
            raise RateNotFound(f"no rates for {currency}")
        days = [r.effective for r in rates]
        i = bisect.bisect_right(days, day) - 1
        if i < 0:
            raise RateNotFound(f"no {currency} rate on or before {day}")
        return rates[i]

    def __len__(self):
        return sum(len(v) for v in self._by_currency.values())


def load_rates(text, *, source="<rates>", base=None):
    """Parse rates-file text into a RateTable."""
    table = None
    pending = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        words = line.split()
        if words[0].lower() == "base":
            if len(words) != 2:
                raise ParseError("base needs one currency", line=number, source=source)
            if table is not None or base is not None:
                raise ParseError("base given twice", line=number, source=source)
            table = RateTable(words[1])
            continue
        if len(words) != 3:
            raise ParseError(f"expected 'date currency value', got {line!r}",
                             line=number, source=source)
        day = parse_iso(words[0], line=number, source=source)
        value = parse_c_decimal(words[2], line=number, source=source, what="rate")
        pending.append((words[1], day, value, number))
    if table is None:
        table = RateTable(base or DEFAULT_BASE)
    for cur, day, value, number in pending:
        table.add(cur, day, value, line=number, source=source)
    return table
