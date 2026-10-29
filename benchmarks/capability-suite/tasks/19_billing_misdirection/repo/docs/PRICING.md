# Pricing

Each plan in `catalog.toml` has a base fee per billing period and one charge per metered
metric. A metric's billed quantity for a period (or plan segment) comes from its aggregation:
`sum` of all records (API calls), `max` reading (peak seats) or `last` reading (end-of-period
storage, ties going to the record that comes later in the feeds).

`included` units are taken off the billed quantity first (never below zero); the rest is
priced with one of five models.

## Tiers and `up_to`

Graduated and volume charges have tiers, each with an `up_to` bound and a `unit_price`
(optionally a `flat_fee`). The bounds increase and the last tier is open (`up_to = "inf"`).

**`up_to` is inclusive.** A tier covers quantities above the previous tier's `up_to` and up
to *and including* its own. With tiers `up_to = 10`, `up_to = 25`, `inf`:

| quantity | tier |
|---|---|
| 10 | first (1-10) |
| 11 | second (11-25) |
| 25 | second (11-25) |
| 26 | third (above 25) |

This is what the sales contracts say ("up to and including 25 seats at $10.00") and is not
negotiable.

## Models

* `per_unit`: quantity x unit price.
* `graduated`: the quantity is split over the tiers and each slice is priced at its own
  tier's price (the first 1,000,000 calls at 0.0004, the next 9,000,000 at 0.00025, ...). A
  tier's flat fee is charged once if any of the quantity falls in it.
* `volume`: the whole quantity is priced at the price of the single tier it falls in (using
  the inclusive bounds above), plus that tier's flat fee. Zero quantity costs nothing.
* `package`: a price per block of `package_size` units; a started block is charged in full.
* `flat`: the unit price once.

Rated amounts are carried at 8 decimal places and only rounded on the invoice line
(docs/INVOICES.md). `python3 -m meterbill rate DATA PLAN METRIC QTY` shows how a quantity is
rated.

## Quotes

`quotes.py` prices expected usage on every plan with the same rating code, pre-tax, so a
quote never disagrees with an invoice.
