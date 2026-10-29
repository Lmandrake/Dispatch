"""Exchange rates (data/fx_rates.csv) and conversion between currencies.

The rate file quotes every currency against USD, the reference currency:

    effective,currency,per_usd
    2026-03-01,EUR,0.9210        # 1 USD = 0.9210 EUR from 1 March on

A quote applies from its effective day until the next quote for the same
currency.  USD itself is always 1.

Cross rates are carried at 10 decimal places (docs/FX.md).  Rate lookups
are frequent (every invoice line, every credit, every row of the
reconciliation report), so ``Converter`` memoises cross rates.
"""

import bisect
from decimal import ROUND_HALF_EVEN, Decimal

from . import currency as _cur
from .csvutil import read_rows
from .errors import ConfigError, RateNotFound
from .money import Money, dec, precise
from .timeutil import parse_date

REFERENCE = "USD"
CROSS_PLACES = Decimal("0.0000000001")


class RateTable:
    """Per-currency, date-sorted USD quotes."""

    def __init__(self):
        self._dates = {}
        self._rates = {}

    def add(self, currency, effective, per_usd):
        code = _cur.get(currency).code
        if code == REFERENCE:
            raise ConfigError("USD is the reference currency and is not quoted")
        per_usd = dec(per_usd)
        if per_usd <= 0:
            raise ConfigError(f"{code} rate on {effective} must be positive")
        dates = self._dates.setdefault(code, [])
        rates = self._rates.setdefault(code, [])
        i = bisect.bisect_left(dates, effective)
        if i < len(dates) and dates[i] == effective:
            raise ConfigError(f"two {code} quotes effective {effective}")
        dates.insert(i, effective)
        rates.insert(i, per_usd)

    def currencies(self):
        return sorted(self._dates)

    def per_usd(self, currency, on):
        """The quote for ``currency`` in effect on date ``on``."""
        code = _cur.get(currency).code
        if code == REFERENCE:
            return Decimal(1)
        dates = self._dates.get(code)
        if not dates:
            raise RateNotFound(code, on)
        i = bisect.bisect_right(dates, on) - 1
        if i < 0:
            raise RateNotFound(code, on)
        return self._rates[code][i]

    def effective_on(self, currency, on):
        """Date from which the quote in effect on ``on`` applies (None for USD)."""
        code = _cur.get(currency).code
        if code == REFERENCE:
            return None
        dates = self._dates.get(code)
        if not dates:
            raise RateNotFound(code, on)
        i = bisect.bisect_right(dates, on) - 1
        if i < 0:
            raise RateNotFound(code, on)
        return dates[i]

    def quotes(self, currency):
        code = _cur.get(currency).code
        return list(zip(self._dates.get(code, []), self._rates.get(code, [])))


def parse_rates(text, *, source="fx_rates.csv"):
    table = RateTable()
    for lineno, r in read_rows(text, required=("effective", "currency", "per_usd"), source=source):
        try:
            day = parse_date(r["effective"])
        except ValueError as e:
            raise ConfigError(f"line {lineno}: {e}", source=source) from None
        try:
            table.add(r["currency"], day, r["per_usd"])
        except (ValueError, TypeError) as e:
            raise ConfigError(f"line {lineno}: {e}", source=source) from None
    return table


class Converter:
    """Converts Money between currencies with one RateTable."""

    def __init__(self, table):
        self.table = table
        self._memo = {}
        self.lookups = 0
        self.hits = 0

    def cross_rate(self, src, dst, on):
        """Units of ``dst`` per one unit of ``src`` on day ``on``."""
        src = _cur.get(src).code
        dst = _cur.get(dst).code
        self.lookups += 1
        if src == dst:
            return Decimal(1)
        key = (src, dst, self.table.effective_on(dst, on))
        if key in self._memo:
            self.hits += 1
            return self._memo[key]
        rate = (self.table.per_usd(dst, on) / self.table.per_usd(src, on)).quantize(
            CROSS_PLACES, rounding=ROUND_HALF_EVEN)
        self._memo[key] = rate
        return rate

    def convert(self, money, dst, on):
        """``money`` expressed in ``dst`` on day ``on`` (PRECISE, unrounded)."""
        dst = _cur.get(dst).code
        if money.currency == dst:
            return money
        rate = self.cross_rate(money.currency, dst, on)
        return Money(precise(money.amount * rate), dst)

    def to_reference(self, money, on):
        return self.convert(money, REFERENCE, on)
