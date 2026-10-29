"""Tax filing summary per jurisdiction (docs/TAX.md, "Filing").

For one billing run: per jurisdiction, the number of invoices, the taxable
amount and the tax, in each invoice currency (tax authorities want the
amounts as invoiced, not converted), plus the reverse-charged net amounts
that must be reported separately (EC sales list).
"""

from dataclasses import dataclass, field

from .money import Money


@dataclass
class JurisdictionTotals:
    code: str
    name: str
    rate: object
    invoices: int = 0
    taxable: dict = field(default_factory=dict)     # currency -> Money
    tax: dict = field(default_factory=dict)
    reverse_charged: dict = field(default_factory=dict)
    reverse_charge_customers: list = field(default_factory=list)

    def _add(self, bucket, m):
        bucket[m.currency] = bucket.get(m.currency, Money.zero(m.currency)) + m


def tax_summary(invoices):
    out = {}
    for inv in invoices:
        rule = inv.tax.rule
        jt = out.get(rule.code)
        if jt is None:
            jt = out[rule.code] = JurisdictionTotals(rule.code, rule.name, rule.rate)
        jt.invoices += 1
        if inv.tax.reverse_charged:
            jt._add(jt.reverse_charged, inv.tax.taxable)
            jt.reverse_charge_customers.append((inv.customer.id, inv.customer.tax_id))
        else:
            jt._add(jt.taxable, inv.tax.taxable)
            jt._add(jt.tax, inv.tax.tax)
    return [out[k] for k in sorted(out)]


def ec_sales_list(invoices):
    """(customer id, tax id, net amount) for reverse-charged invoices, by customer."""
    rows = []
    for inv in invoices:
        if inv.tax.reverse_charged:
            rows.append((inv.customer.id, inv.customer.tax_id, inv.tax.taxable))
    return sorted(rows, key=lambda r: r[0])


def render_tax_summary(totals):
    from .render.fmt import format_amount
    out = [f"{'jurisdiction':<14}{'rate':>8}{'inv':>5}  {'taxable':>16}  {'tax':>14}"]
    for jt in totals:
        currencies = sorted(set(jt.taxable) | set(jt.reverse_charged)) or ["-"]
        first = True
        for cur in currencies:
            taxable = jt.taxable.get(cur)
            tax = jt.tax.get(cur)
            rc = jt.reverse_charged.get(cur)
            left = f"{jt.code:<14}{(jt.rate * 100).normalize():>7f}%{jt.invoices:>5}" if first else " " * 27
            if taxable is not None:
                out.append(f"{left}  {format_amount(taxable) + ' ' + cur:>16}  {format_amount(tax) + ' ' + cur:>14}")
            if rc is not None:
                out.append(f"{left if taxable is None else ' ' * 27}  {format_amount(rc) + ' ' + cur:>16}  {'reverse charge':>14}")
            first = False
    return "\n".join(out) + "\n"
