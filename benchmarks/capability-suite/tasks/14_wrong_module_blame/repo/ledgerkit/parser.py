"""Turn lexed lines into a Ledger: entries, chart of accounts, splits.

Entry fields, in order::

    date | account | description | amount [| currency [| tags]]

* ``date`` in the active locale's formats (ISO always works);
* ``account`` is resolved through the chart (aliases, abbreviations), or is
  ``@name`` to allocate the amount over a declared split;
* ``amount`` in the active locale's number convention (see amounts.py);
* ``currency`` defaults to the ``!currency`` directive, else the base currency;
* ``tags`` are comma-separated words, stored lower-case, sorted, de-duplicated.

Directives::

    !locale de_DE                  switch number/date convention (rest of file)
    !currency EUR                  default currency for entries that omit it
    !account Expenses:Travel:Air   declare an account
    !alias air Expenses:Travel:Air declare an alias
    !strict                        unknown accounts are errors from here on
    !split rent Expenses:Rent:HQ=3 Expenses:Rent:Lab=1
                                   declare split "rent"; shares are C decimals
    !tag audit                     add a tag to every following entry
    !endtag audit                  stop adding it
"""

from dataclasses import dataclass, field

from .accounts import Chart
from .dates import parse_date
from .errors import AllocationError, ParseError
from .lexer import tokenize
from .locales import get_locale
from .models import RawEntry
from .amounts import parse_amount, parse_c_decimal

MIN_FIELDS = 4
MAX_FIELDS = 6


@dataclass
class Split:
    name: str
    shares: tuple            # ((account, Decimal share), ...) in declaration order
    line: int = 0

    @property
    def accounts(self):
        return [a for a, _ in self.shares]


@dataclass
class Ledger:
    entries: list = field(default_factory=list)
    chart: Chart = field(default_factory=Chart)
    splits: dict = field(default_factory=dict)
    source: str = "<memory>"

    def __len__(self):
        return len(self.entries)

    def currencies(self):
        return sorted({e.currency for e in self.entries})


class _State:
    def __init__(self, locale, currency):
        self.locale = get_locale(locale)
        self.currency = currency
        self.tags = []


def parse_ledger(text, *, source="<memory>", locale=None, base_currency="USD",
                 chart=None, strict=False):
    """Parse ledger ``text`` and return a Ledger."""
    ledger = Ledger(chart=chart if chart is not None else Chart(strict=strict), source=source)
    state = _State(locale, base_currency.upper())
    for line in tokenize(text, source=source):
        if line.kind == "directive":
            _directive(line, state, ledger, source)
        else:
            ledger.entries.append(_entry(line, state, ledger, source))
    return ledger


def _directive(line, state, ledger, source):
    name, args = line.fields[0].lower(), list(line.fields[1:])
    n = line.number

    def need(count):
        if len(args) != count:
            raise ParseError(f"!{name} takes {count} argument(s)", line=n, source=source)

    if name == "locale":
        need(1)
        state.locale = get_locale(args[0])
    elif name == "currency":
        need(1)
        cur = args[0].upper()
        if not (cur.isalpha() and len(cur) == 3):
            raise ParseError(f"bad currency {args[0]!r}", line=n, source=source)
        state.currency = cur
    elif name == "account":
        need(1)
        ledger.chart.declare(args[0], line=n, source=source)
    elif name == "alias":
        need(2)
        ledger.chart.add_alias(args[0], args[1], line=n, source=source)
    elif name == "strict":
        need(0)
        ledger.chart.strict = True
    elif name == "split":
        _split_directive(args, ledger, n, source)
    elif name == "tag":
        need(1)
        tag = args[0].lower()
        if tag not in state.tags:
            state.tags.append(tag)
    elif name == "endtag":
        need(1)
        tag = args[0].lower()
        if tag not in state.tags:
            raise ParseError(f"!endtag {tag} without !tag", line=n, source=source)
        state.tags.remove(tag)
    else:
        raise ParseError(f"unknown directive !{name}", line=n, source=source)


def _split_directive(args, ledger, n, source):
    if len(args) < 2:
        raise ParseError("!split needs a name and at least one account=share",
                         line=n, source=source)
    split_name = args[0].lower()
    if split_name in ledger.splits:
        raise ParseError(f"split {split_name!r} declared twice", line=n, source=source)
    shares = []
    for word in args[1:]:
        if "=" not in word:
            raise ParseError(f"expected account=share, got {word!r}", line=n, source=source)
        acct, share = word.rsplit("=", 1)
        canonical = ledger.chart.resolve(acct, line=n, source=source)
        value = parse_c_decimal(share, line=n, source=source, what="share")
        if value < 0:
            raise AllocationError(f"negative share for {canonical}", line=n, source=source)
        if any(a == canonical for a, _ in shares):
            raise AllocationError(f"{canonical} listed twice in split", line=n, source=source)
        shares.append((canonical, value))
    if sum(v for _, v in shares) == 0:
        raise AllocationError(f"split {split_name!r} has no positive share",
                              line=n, source=source)
    ledger.splits[split_name] = Split(split_name, tuple(shares), n)


def _entry(line, state, ledger, source):
    fields = list(line.fields)
    n = line.number
    if not (MIN_FIELDS <= len(fields) <= MAX_FIELDS):
        raise ParseError(f"expected {MIN_FIELDS}-{MAX_FIELDS} fields, got {len(fields)}",
                         line=n, source=source)
    while len(fields) < MAX_FIELDS:
        fields.append("")
    date_s, acct_s, desc, amount_s, cur_s, tags_s = fields
    on = parse_date(date_s, state.locale, line=n, source=source)
    if acct_s.startswith("@"):
        key = acct_s[1:].strip().lower()
        if key not in ledger.splits:
            raise ParseError(f"unknown split {acct_s!r}", line=n, source=source)
        account = "@" + key
    else:
        account = ledger.chart.resolve(acct_s, line=n, source=source)
    amount = parse_amount(amount_s, state.locale, line=n, source=source)
    currency = (cur_s or state.currency).upper()
    if not (currency.isalpha() and len(currency) == 3):
        raise ParseError(f"bad currency {cur_s!r}", line=n, source=source)
    tags = set(state.tags)
    for t in tags_s.split(","):
        t = t.strip().lower()
        if t:
            tags.add(t)
    return RawEntry(line=n, on=on, account=account, description=desc, amount=amount,
                    currency=currency, tags=tuple(sorted(tags)), source=source)
