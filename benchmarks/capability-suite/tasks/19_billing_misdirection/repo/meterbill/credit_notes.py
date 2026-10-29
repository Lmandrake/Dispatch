"""Credit notes for corrected invoices (docs/INVOICES.md, "Corrections").

When an issued invoice turns out to be wrong it is never edited.  Instead:

1. a credit note ``CN-<invoice number>`` reverses the original in full, and
2. a re-issued invoice ``<number>-R<n>`` is sent with the right figures.

For the customer's convenience the credit note also carries a *difference*
section, line by line (matched on kind + description), so they can see what
changed.  ``net_change`` is new total - old total.
"""

from dataclasses import dataclass, field

from .money import Money


@dataclass(frozen=True)
class LineChange:
    kind: str
    description: str
    old: Money
    new: Money

    @property
    def delta(self):
        return self.new - self.old


@dataclass
class CreditNote:
    number: str
    original: str
    reissue: str
    currency: str
    reversed_total: Money
    changes: list = field(default_factory=list)
    net_change: Money = None

    def changed_lines(self):
        return [c for c in self.changes if c.delta]


def _index(inv):
    out = {}
    for ln in inv.lines:
        key = (ln.kind, ln.description)
        out[key] = out.get(key, Money.zero(inv.currency)) + ln.amount
    return out


def credit_note(original, corrected):
    if original.currency != corrected.currency:
        raise ValueError("a correction cannot change the invoice currency")
    if original.customer.id != corrected.customer.id:
        raise ValueError("a correction cannot change the customer")
    cur = original.currency
    old = _index(original)
    new = _index(corrected)
    keys = list(old)
    for k in new:
        if k not in old:
            keys.append(k)
    changes = [LineChange(k[0], k[1], old.get(k, Money.zero(cur)), new.get(k, Money.zero(cur))) for k in keys]
    for label, a, b in (("discount", original.discount_total, corrected.discount_total),
                        ("tax", original.tax.tax, corrected.tax.tax)):
        changes.append(LineChange(label, label, a, b))
    return CreditNote(
        number=f"CN-{original.number}",
        original=original.number,
        reissue=corrected.number,
        currency=cur,
        reversed_total=-original.total,
        changes=changes,
        net_change=corrected.total - original.total,
    )


def render_credit_note(cn):
    from .render.fmt import format_amount
    out = [f"CREDIT NOTE {cn.number}", f"Reverses {cn.original}; replaced by {cn.reissue}", ""]
    out.append(f"{'Reversal of ' + cn.original:<56}{format_amount(cn.reversed_total):>16}")
    out.append("")
    out.append("What changed:")
    for c in cn.changed_lines():
        out.append(f"  {c.description[:44]:<44}{format_amount(c.old):>12}{format_amount(c.new):>12}{format_amount(c.delta):>12}")
    if not cn.changed_lines():
        out.append("  (no line changed)")
    out.append("")
    out.append(f"{'Net change ' + cn.currency:<56}{format_amount(cn.net_change):>16}")
    return "\n".join(out) + "\n"
