"""Normalise parsed entries into Postings in the base currency.

For every RawEntry:

1. the exchange rate in effect on the entry's date is looked up (see
   rates.py: a rate applies from its effective day onward);
2. the amount is converted, ``amount * rate``, and quantized to MICRO
   (six places, half-even);
3. an entry booked to a split (``@name``) is expanded into one Posting per
   account of the split, the converted amount being allocated in proportion
   to the shares (see ``allocate``);
4. the posting gets its reporting period label (month, quarter or year).

The converted amounts of the postings produced from one entry always add up
exactly to the converted amount of the entry.
"""

from decimal import Decimal

from .dates import period_of
from .errors import AllocationError, RateNotFound
from .money import MICRO, ZERO, to_micro
from .models import Posting


def allocate(amount, shares):
    """Split ``amount`` over ``shares`` (a list of (key, Decimal weight)).

    Each part is ``amount * weight / sum(weights)`` truncated toward zero to
    MICRO; the micro-units left over are handed out one at a time to the parts
    with the largest discarded remainders (ties: earlier key first).  The parts
    sum exactly to ``to_micro(amount)``.  Zero weights get exactly zero.
    Returns a list of (key, Decimal) in the order given.
    """
    if not shares:
        raise AllocationError("nothing to allocate to")
    weights = [w for _, w in shares]
    if any(w < 0 for w in weights):
        raise AllocationError("negative weight")
    whole = sum(weights, ZERO)
    if whole == 0:
        raise AllocationError("all weights are zero")
    target = to_micro(amount)
    sign = -1 if target < 0 else 1
    units = int((abs(target) / MICRO).to_integral_value())
    raw = [Decimal(units) * w / whole for w in weights]
    floors = [int(r) for r in raw]
    left = units - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:left]:
        floors[i] += 1
    return [(key, sign * Decimal(f) * MICRO) for (key, _), f in zip(shares, floors)]


class Normalizer:
    """Converts RawEntries of one ledger with one rate table."""

    def __init__(self, rates, *, splits=None, period="month"):
        self.rates = rates
        self.splits = splits or {}
        self.period = period
        self._rate_memo = {}
        self.lookups = 0

    @property
    def base(self):
        return self.rates.base

    def rate_for(self, currency, day):
        """The Decimal rate for ``currency`` on ``day`` (memoised)."""
        # Rate tables are small but ledgers are not: look each rate up once
        # per currency and reporting period instead of once per entry.
        key = (currency, period_of(day, self.period))
        hit = self._rate_memo.get(key)
        if hit is None:
            self.lookups += 1
            hit = self.rates.rate_on(currency, day).value
            self._rate_memo[key] = hit
        return hit

    def convert_amount(self, amount, currency, day):
        """``amount`` of ``currency`` on ``day`` in the base currency, at MICRO."""
        rate = self.rate_for(currency, day)
        return to_micro(amount * rate), rate

    def postings_for(self, entry):
        """The Posting(s) for one RawEntry."""
        try:
            converted, rate = self.convert_amount(entry.amount, entry.currency, entry.on)
        except RateNotFound as exc:
            raise RateNotFound(exc.bare_message, line=entry.line, source=entry.source) from None
        period = period_of(entry.on, self.period)
        if entry.account.startswith("@"):
            split = self.splits[entry.account[1:]]
            parts = allocate(converted, list(split.shares))
            originals = dict(allocate(entry.amount, list(split.shares)))
            return [
                Posting(line=entry.line, on=entry.on, period=period, account=acct,
                        description=entry.description, amount=part,
                        original_amount=originals[acct],
                        original_currency=entry.currency, rate=rate, tags=entry.tags)
                for acct, part in parts
            ]
        return [Posting(line=entry.line, on=entry.on, period=period, account=entry.account,
                        description=entry.description, amount=converted,
                        original_amount=entry.amount, original_currency=entry.currency,
                        rate=rate, tags=entry.tags)]

    def run(self, entries):
        out = []
        for entry in entries:
            out.extend(self.postings_for(entry))
        return out


def normalize(ledger, rates, *, period="month"):
    """Postings for every entry of ``ledger`` (see module docstring)."""
    return Normalizer(rates, splits=ledger.splits, period=period).run(ledger.entries)
