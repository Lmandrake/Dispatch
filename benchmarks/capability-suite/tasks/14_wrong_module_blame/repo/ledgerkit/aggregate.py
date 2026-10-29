"""Sum postings into per-account, per-period totals.

``aggregate`` returns a Totals object holding the *leaf* totals: one Decimal
per (account, period) for every account that has postings.  Totals for parent
accounts (``Expenses`` for ``Expenses:Travel:Air``) and the grand total are
derived by rolling the leaves up the account tree.

All arithmetic is exact Decimal arithmetic; nothing here rounds.  (The report
rounds every displayed number independently, so a displayed parent total may
differ by a cent from the sum of its displayed children: that is expected and
is what the books show.)
"""

import math
from collections import defaultdict

from .accounts import ancestors, truncate
from .dates import sort_periods
from .money import ZERO, total


class Totals:
    """Leaf totals plus derived roll-ups."""

    def __init__(self, leaves, periods):
        self._leaves = leaves                    # account -> {period: Decimal}
        self.periods = sort_periods(periods)
        self._rolled = None

    # -- leaves --------------------------------------------------------------
    def accounts(self):
        """Accounts that carry postings, sorted."""
        return sorted(self._leaves)

    def leaf(self, account, period=None):
        cells = self._leaves.get(account, {})
        if period is None:
            return total(cells.values())
        return cells.get(period, ZERO)

    # -- roll-ups ------------------------------------------------------------
    def _rollup(self):
        if self._rolled is None:
            self._rolled = rollup(self._leaves)
        return self._rolled

    def tree(self):
        """Every account with postings plus all its ancestors, sorted."""
        return sorted(self._rollup())

    def balance(self, account, period=None):
        """Total of ``account`` and all its descendants (one period or all)."""
        cells = self._rollup().get(account)
        if cells is None:
            return ZERO
        if period is None:
            return _combine(cells.values())
        return cells.get(period, ZERO)

    def by_period(self, account):
        cells = self._rollup().get(account, {})
        return {p: cells.get(p, ZERO) for p in self.periods}

    def top_level(self):
        return sorted(a for a in self._rollup() if ":" not in a)

    def grand(self, period=None):
        """Sum over the top-level accounts."""
        if period is None:
            return _combine(self.balance(a) for a in self.top_level())
        return _combine(self.balance(a, period) for a in self.top_level())


def _combine(values):
    # Roll-ups can add thousands of postings; math.fsum keeps the full
    # precision of every term (no accumulated rounding error).
    return _as_decimal(math.fsum(values))


def _as_decimal(x):
    from decimal import Decimal
    return Decimal(x)


def rollup(leaves):
    """account -> {period: Decimal} for leaves and every ancestor account."""
    contributions = defaultdict(lambda: defaultdict(list))
    for account, cells in leaves.items():
        for period, amount in cells.items():
            contributions[account][period].append(amount)
            for parent in ancestors(account):
                contributions[parent][period].append(amount)
    out = {}
    for account, cells in contributions.items():
        if account in leaves and not any(a.startswith(account + ":") for a in leaves):
            out[account] = dict(leaves[account])
        else:
            out[account] = {p: _combine(vals) for p, vals in cells.items()}
    return out


def aggregate(postings, *, depth=None, tags=None, exclude_tags=None, accounts=None):
    """Totals over ``postings``.

    depth         truncate account names to this many components first
    tags          keep only postings carrying at least one of these tags
    exclude_tags  drop postings carrying any of these tags
    accounts      keep only postings whose account equals or is under one of these
    """
    want = {t.lower() for t in tags} if tags else None
    drop = {t.lower() for t in exclude_tags} if exclude_tags else set()
    roots = tuple(accounts) if accounts else None
    leaves = defaultdict(lambda: defaultdict(lambda: ZERO))
    periods = set()
    for p in postings:
        if want is not None and not want.intersection(p.tags):
            continue
        if drop.intersection(p.tags):
            continue
        if roots is not None and not any(p.account == r or p.account.startswith(r + ":")
                                         for r in roots):
            continue
        acct = truncate(p.account, depth)
        leaves[acct][p.period] += p.amount
        periods.add(p.period)
    return Totals({a: dict(c) for a, c in leaves.items()}, periods)


def per_currency(postings):
    """Original-currency totals: currency -> Decimal (not converted)."""
    out = defaultdict(lambda: ZERO)
    for p in postings:
        out[p.original_currency] += p.original_amount
    return dict(out)


def largest(postings, n=5, *, account=None):
    """The ``n`` postings with the largest absolute base amount.

    Ties are broken by date, then line number, so the result is deterministic.
    """
    pool = [p for p in postings
            if account is None or p.account == account or p.account.startswith(account + ":")]
    pool.sort(key=lambda p: (-abs(p.amount), p.on, p.line))
    return pool[:n]
