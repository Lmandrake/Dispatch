# Tax

`tax.toml` has one entry per jurisdiction: `rate`, `rounding` (`per_invoice` or `per_line`),
rounding `mode` (`half_up` by default; `half_even`, `down`, ...), `reverse_charge` and the
`label` printed on the invoice.

* `per_invoice`: tax = round(taxable x rate).
* `per_line`: the invoice's discount is spread over the taxable lines in proportion to their
  amounts (largest-remainder, in minor units), each line's tax is round((line - its share) x
  rate), and the tax is the sum of the line taxes.
* Reverse charge: in a jurisdiction with `reverse_charge = true`, a customer with a tax id
  pays no VAT and the invoice carries the reverse-charge note.

## Jurisdiction

A customer record can name three regions: `jurisdiction` (the region of the billing address,
always present), `service_region` (where the service is used, optional) and `tax_override`
(set by the tax team after a ruling, optional). Since the 2025 destination-based rules, the
jurisdiction that applies is, in this order of precedence:

1. `tax_override`, when set;
2. otherwise `service_region`, when set;
3. otherwise `jurisdiction`, the billing address.

A region that is a subdivision missing from the tax table (`US-WA`) falls back to its country
(`US`) when the country is in the table; a region that resolves to nothing is skipped and the
next one in the order is tried. A customer none of whose regions resolves cannot be invoiced.

## Taxable amount

The taxable amount is the subtotal minus coupons (docs/DISCOUNTS.md). Late fees are not
taxable. Credits do not change the taxable amount.
