# Reconciliation

`python3 -m meterbill recon DATA CYCLE` prints, per customer: the usage records that fall in
the period, how many were billed and unbilled, how many feed rows naming the customer were
rejected, and the invoice total and amount due in USD (rate of the period's last day, rounded
half-up). Then a totals row, a line with file, record, replay and reject counts, and every
rejected row with its reason.

Finance signs off the reconciliation together with the invoices: the record counts must
match the feeds, and every rejected row must be explainable.

## Audit

`audit.py` records each exported run (cycle, invoice count, USD totals, record and reject
counts, and a digest of every invoice's JSON). Two runs over the same data must give the same
digest.

## Explaining a figure

`python3 -m meterbill explain DATA CYCLE CUSTOMER [--line N]` re-derives invoice lines step
by step: the period's UTC bounds, the records assigned, the aggregation, the rating slices,
the conversion and the rounding.
