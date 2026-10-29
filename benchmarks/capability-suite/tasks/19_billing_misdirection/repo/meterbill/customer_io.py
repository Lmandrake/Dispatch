"""Customer export to CSV, and a field-by-field diff of two customer files.

``customers_to_csv`` writes the same columns ``customers.parse_customers``
reads, in a fixed order (``COLUMNS``), one row per customer sorted by id, so
that exporting an unchanged book twice gives byte-identical files and a
re-import gives back equal Customer objects.

``diff_customers(old, new)`` is for audit: given two dicts id -> Customer
(``parse_customers`` output) it reports customers added, removed, and, for
those in both, each field whose value changed.  ``render_diff`` prints that
as text; ``diff_customer_files`` parses two texts first, so a malformed file
raises ConfigError exactly as it would when billing.

Comparing is by field value after the parser's normalisation (ids and
jurisdictions upper-cased, tax ids without spaces), so a change that only
differs in case or spacing in the source file is not reported.
"""

from dataclasses import dataclass, field, fields

from .csvutil import write_rows
from .customers import Customer, parse_customers

COLUMNS = ("id", "name", "timezone", "anchor_day", "currency", "jurisdiction", "service_region",
           "tax_override", "tax_id", "email", "terms_days", "status")

assert set(COLUMNS) == {f.name for f in fields(Customer)}, "COLUMNS out of step with Customer"


def customer_row(c):
    """The CSV row of one customer, in COLUMNS order."""
    return tuple(str(getattr(c, name)) for name in COLUMNS)


def customers_to_csv(customers):
    """CSV text for ``customers`` (a dict id -> Customer, a CustomerBook or any iterable)."""
    values = customers.values() if isinstance(customers, dict) else customers
    return write_rows(COLUMNS, [customer_row(c) for c in sorted(values, key=lambda c: c.id)])


@dataclass(frozen=True)
class FieldChange:
    name: str
    old: str
    new: str


@dataclass
class CustomerDiff:
    added: list = field(default_factory=list)       # [Customer]
    removed: list = field(default_factory=list)     # [Customer]
    changed: dict = field(default_factory=dict)     # id -> [FieldChange]

    @property
    def empty(self):
        return not (self.added or self.removed or self.changed)

    def changes_to(self, name):
        """All (customer id, FieldChange) where field ``name`` changed."""
        return [(cid, ch) for cid, chs in sorted(self.changed.items()) for ch in chs if ch.name == name]


def diff_customers(old, new):
    """Compare two id -> Customer mappings."""
    diff = CustomerDiff()
    for cid in sorted(set(new) - set(old)):
        diff.added.append(new[cid])
    for cid in sorted(set(old) - set(new)):
        diff.removed.append(old[cid])
    for cid in sorted(set(old) & set(new)):
        a, b = old[cid], new[cid]
        changes = [FieldChange(name, str(getattr(a, name)), str(getattr(b, name)))
                   for name in COLUMNS if getattr(a, name) != getattr(b, name)]
        if changes:
            diff.changed[cid] = changes
    return diff


def diff_customer_files(old_text, new_text, *, old_source="old/customers.csv", new_source="new/customers.csv"):
    """Parse two customers.csv texts (ConfigError on a bad one) and diff them."""
    return diff_customers(parse_customers(old_text, source=old_source),
                          parse_customers(new_text, source=new_source))


def _show(value):
    return value if value != "" else "(empty)"


def render_diff(diff):
    """Plain-text audit report; "No differences." when the files agree."""
    if diff.empty:
        return "No differences.\n"
    out = [f"Customers added: {len(diff.added)}, removed: {len(diff.removed)}, changed: {len(diff.changed)}"]
    for c in diff.added:
        out.append(f"+ {c.id}  {c.name} ({c.currency}, {c.jurisdiction}, {c.status})")
    for c in diff.removed:
        out.append(f"- {c.id}  {c.name} ({c.currency}, {c.jurisdiction}, {c.status})")
    for cid, changes in sorted(diff.changed.items()):
        out.append(f"~ {cid}")
        for ch in changes:
            out.append(f"    {ch.name}: {_show(ch.old)} -> {_show(ch.new)}")
    return "\n".join(out) + "\n"
