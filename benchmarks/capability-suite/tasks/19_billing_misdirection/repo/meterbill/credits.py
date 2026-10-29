"""Prepaid account credit (data/credits.csv), per docs/DISCOUNTS.md ("Credits").

    customer,grant_id,currency,amount,granted,expires
    C09,G-1001,EUR,250.00,2025-12-01,2026-12-01

Credit is money the customer has already paid: it is applied AFTER tax, to
the invoice total, and never reduces the taxable amount.

* Grants are used in order of expiry (soonest first; never-expiring last),
  then by grant id.
* A grant in another currency is converted to the invoice currency at the
  rate of the period's last day.
* Usage stops when the amount due reaches zero.  What is left of each grant
  (in the grant's own currency, rounded down) is reported on the invoice.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN

from .csvutil import read_rows
from .errors import ConfigError, UnknownCustomer
from .money import ZERO, Money, dec, round_to
from .timeutil import parse_date

FAR_FUTURE = date(9999, 12, 31)


@dataclass(frozen=True)
class Grant:
    customer: str
    grant_id: str
    currency: str
    amount: object      # Decimal, grant currency
    granted: date
    expires: date | None = None

    def usable_on(self, day):
        return self.granted <= day and (self.expires is None or day <= self.expires)


@dataclass(frozen=True)
class CreditUse:
    grant: Grant
    applied: Money        # invoice currency, rounded
    remaining: Money      # grant currency, rounded down


def parse_credits(text, *, customers=None, source="credits.csv"):
    out = []
    ids = set()
    for lineno, r in read_rows(text, required=("customer", "grant_id", "currency", "amount", "granted"),
                               optional=("expires",), source=source):
        cid = r["customer"].upper()
        if customers is not None and cid not in customers:
            raise UnknownCustomer(f"{source} line {lineno}: unknown customer {cid}")
        if r["grant_id"] in ids:
            raise ConfigError(f"line {lineno}: duplicate grant id {r['grant_id']}", source=source)
        ids.add(r["grant_id"])
        amount = dec(r["amount"])
        if amount <= 0:
            raise ConfigError(f"line {lineno}: grant amount must be positive", source=source)
        granted = parse_date(r["granted"])
        expires = parse_date(r["expires"]) if r["expires"] else None
        if expires is not None and expires <= granted:
            raise ConfigError(f"line {lineno}: grant expires before it is granted", source=source)
        out.append(Grant(cid, r["grant_id"], Money(amount, r["currency"]).currency, amount, granted, expires))
    return out


def usable_grants(grants, cid, day):
    usable = [g for g in grants if g.customer == cid and g.usable_on(day)]
    return sorted(usable, key=lambda g: (g.expires or FAR_FUTURE, g.grant_id))


def apply_credits(grants, due, converter, rate_day):
    """Apply grants to a rounded Money ``due``; returns (uses, still_due)."""
    cur = due.currency
    uses = []
    left = due
    for g in grants:
        balance = Money(g.amount, g.currency)
        if not left or left.is_negative():
            uses.append(CreditUse(g, Money.zero(cur), Money(round_to(g.amount, g.currency, ROUND_DOWN), g.currency)))
            continue
        avail = converter.convert(balance, cur, rate_day)
        avail = Money(round_to(avail.amount, cur, ROUND_DOWN), cur)
        take = avail if avail <= left else left
        if take == avail:
            remaining = Money.zero(g.currency)
        else:
            back = converter.convert(take, g.currency, rate_day)
            rem = g.amount - back.amount
            remaining = Money(round_to(max(rem, ZERO), g.currency, ROUND_DOWN), g.currency)
        left = left - take
        uses.append(CreditUse(g, take, remaining))
    return uses, left
