"""Plain data records passed between pipeline stages.

Stage boundaries:

    lexer      text line          -> list[str] fields
    parser     fields             -> RawEntry      (strings resolved, nothing converted)
    normalize  RawEntry           -> Posting       (account canonical, amount in base currency)
    aggregate  list[Posting]      -> totals (Decimal, unrounded)
    report     totals             -> Report / text (the only place money is rounded to cents)

Amounts are always ``decimal.Decimal``; nothing upstream of the report rounds to
cents.  Converted amounts carry six decimal places.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class RawEntry:
    """One ledger line after parsing, before any conversion."""

    line: int
    on: date
    account: str
    description: str
    amount: Decimal
    currency: str
    tags: tuple = ()
    source: str = "<memory>"

    def with_amount(self, amount):
        return replace(self, amount=amount)


@dataclass(frozen=True)
class Posting:
    """A normalised entry: canonical account, amount in the base currency."""

    line: int
    on: date
    period: str
    account: str
    description: str
    amount: Decimal          # in the base currency, six decimal places
    original_amount: Decimal
    original_currency: str
    rate: Decimal
    tags: tuple = ()

    @property
    def top_account(self):
        return self.account.split(":", 1)[0]

    def has_tag(self, tag):
        return tag in self.tags


@dataclass(frozen=True)
class Rate:
    currency: str
    effective: date
    value: Decimal          # units of base currency per one unit of `currency`


@dataclass
class ReportRow:
    label: str
    cells: dict = field(default_factory=dict)     # period -> Decimal
    total: Decimal = Decimal("0")
    indent: int = 0
    is_total: bool = False


@dataclass
class Report:
    title: str
    base_currency: str
    periods: list
    rows: list
    grand: ReportRow
    notes: list = field(default_factory=list)
