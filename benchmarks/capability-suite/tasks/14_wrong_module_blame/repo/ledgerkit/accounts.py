"""Chart of accounts: canonical names, aliases and abbreviation lookup.

Account names are colon-separated paths whose first component is one of the
five account types (``Assets``, ``Liabilities``, ``Equity``, ``Income``,
``Expenses``).  Each component starts with a capital letter or a digit.

Lookup order for a name written in a ledger entry:

1. an exact canonical name;
2. an alias declared with ``!alias`` (case-insensitive);
3. a case-insensitive match of every component;
4. an unambiguous abbreviation: each written component is a prefix of the
   corresponding component of exactly one declared account
   (``exp:trav`` -> ``Expenses:Travel``).

When the chart is *strict*, a name that resolves to nothing is an error.  When
it is not strict, an unknown but well-formed name is declared on first use.
"""

import re

from .errors import AccountError

ACCOUNT_TYPES = ("Assets", "Liabilities", "Equity", "Income", "Expenses")
_COMPONENT = re.compile(r"^[A-Z0-9][A-Za-z0-9&'\- ]*$")


def split_name(name):
    return [part.strip() for part in name.split(":")]


def is_valid_name(name):
    parts = split_name(name)
    if not parts or parts[0] not in ACCOUNT_TYPES:
        return False
    return all(_COMPONENT.match(p) for p in parts)


def parent_of(name):
    """``Expenses:Travel:Air`` -> ``Expenses:Travel``; top level -> None."""
    if ":" not in name:
        return None
    return name.rsplit(":", 1)[0]


def ancestors(name):
    """All proper ancestors, nearest first."""
    out = []
    cur = parent_of(name)
    while cur is not None:
        out.append(cur)
        cur = parent_of(cur)
    return out


def truncate(name, depth):
    """Keep the first ``depth`` components (depth <= 0 keeps all)."""
    if depth is None or depth <= 0:
        return name
    return ":".join(split_name(name)[:depth])


class Chart:
    """The set of known accounts plus aliases."""

    def __init__(self, strict=False):
        self.strict = strict
        self._accounts = {}          # canonical name -> declared line (or None)
        self._aliases = {}           # lowercase alias -> canonical name
        self._lower = {}             # lowercase canonical -> canonical

    # -- declaration -------------------------------------------------------
    def declare(self, name, *, line=None, source=None):
        name = ":".join(split_name(name))
        if not is_valid_name(name):
            raise AccountError(f"invalid account name {name!r}", line=line, source=source)
        if name not in self._accounts:
            self._accounts[name] = line
            self._lower[name.lower()] = name
        return name

    def add_alias(self, alias, target, *, line=None, source=None):
        key = alias.strip().lower()
        if not key:
            raise AccountError("empty alias", line=line, source=source)
        if ":" in key:
            raise AccountError(f"alias {alias!r} must not contain ':'", line=line, source=source)
        canonical = self.resolve(target, line=line, source=source)
        existing = self._aliases.get(key)
        if existing is not None and existing != canonical:
            raise AccountError(f"alias {alias!r} already points to {existing}",
                               line=line, source=source)
        self._aliases[key] = canonical
        return canonical

    # -- queries -----------------------------------------------------------
    def __contains__(self, name):
        return name in self._accounts

    def __iter__(self):
        return iter(sorted(self._accounts))

    def __len__(self):
        return len(self._accounts)

    def aliases(self):
        return dict(self._aliases)

    def resolve(self, written, *, line=None, source=None):
        """Return the canonical account for ``written`` (see module docstring)."""
        name = ":".join(split_name(written))
        if not name:
            raise AccountError("empty account", line=line, source=source)
        if name in self._accounts:
            return name
        lowered = name.lower()
        if lowered in self._aliases:
            return self._aliases[lowered]
        if lowered in self._lower:
            return self._lower[lowered]
        matches = self._abbreviation_matches(name)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AccountError(f"ambiguous account {written!r}: " + ", ".join(matches),
                               line=line, source=source)
        if self.strict:
            raise AccountError(f"unknown account {written!r}", line=line, source=source)
        return self.declare(name, line=line, source=source)

    def _abbreviation_matches(self, name):
        want = [p.lower() for p in split_name(name)]
        if any(not p for p in want):
            return []
        found = []
        for canonical in self._accounts:
            have = [p.lower() for p in split_name(canonical)]
            if len(have) != len(want):
                continue
            if all(h.startswith(w) for h, w in zip(have, want)):
                found.append(canonical)
        return sorted(found)

    def children(self, name):
        prefix = name + ":"
        return sorted(a for a in self._accounts if a.startswith(prefix)
                      and ":" not in a[len(prefix):])

    def with_ancestors(self):
        """Every declared account plus all of their ancestors, sorted."""
        out = set(self._accounts)
        for a in list(self._accounts):
            out.update(ancestors(a))
        return sorted(out)
