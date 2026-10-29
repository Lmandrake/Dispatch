# Invoices

## How an invoice is computed

1. The billing period in the customer's timezone (docs/PERIODS.md).
2. Plan segments from the subscription history (docs/SUBSCRIPTIONS.md).
3. Usage assigned to segments and aggregated per metric (docs/PRICING.md).
4. Lines, segment by segment: the prorated base fee, then each metered charge of the plan in
   catalogue order. Each amount is computed in the plan currency at 8 decimal places,
   converted to the invoice currency at the rate of the period's last day (docs/FX.md), and
   then rounded half-up to the currency's minor unit. The rounded line amount is final.
5. Subtotal: the sum of the rounded line amounts.
6. Coupons, before tax (docs/DISCOUNTS.md).
7. Tax on subtotal minus coupons (docs/TAX.md).
8. Total = subtotal - coupons + tax + late fees.
9. Credits; what remains is the amount due.

## Rounding

There is exactly one rounding per printed figure, and it happens in steps 4 to 7 above.
Everything after that is exact addition of rounded amounts, so every invoice adds up to the
cent as printed.

## Rendering

The renderers (`render/text.py`, `render/csv_out.py`, `render/json_out.py`) only format.
They never compute, convert or round an amount: every figure they print is a field of the
`Invoice`. `render/fmt.py` pads amounts to the currency's number of decimals; it does not
change values, and `format_amount(..., strict=True)` raises if it is ever handed an amount
that is not already rounded.

The text invoice is 72 columns: description left, amount right-aligned in the last 14. Tier
details are printed under a usage line. The CSV and JSON forms carry the same figures.

## Numbers

`KC-<cycle>-<customer>`; a corrected re-issue gets `-R1`, `-R2`, ...

## Corrections

An issued invoice is never edited. `credit_notes.py` reverses it in full and lists what changed
against the re-issued one.

## Statements

`statements.py` lists a customer's open receivables and the current invoice with a running
balance.
