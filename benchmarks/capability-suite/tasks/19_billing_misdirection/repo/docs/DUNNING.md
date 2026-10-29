# Dunning

`receivables.csv` lists issued invoices with their due date and payment date (empty when
unpaid). `dunning.toml` lists steps, each a number of days after the due date: `reminder`,
`late_fee` (percent of the open amount, at least a minimum converted from USD at the step
date's rate) and `suspend`.

Dunning is evaluated once per cycle, on the cycle's **dunning date**: the earliest issue date
of the cycle over the active and suspended customers (closed customers do not count). A
step is reached when that date is on or after due + days and the invoice was still unpaid on
the step's date. A late fee is billed once: when the
late-fee step's date is on or before the previous cycle's dunning date, the fee was already on
that cycle's invoice and is not billed again (the step still counts as reached).
Late fees appear on the next invoice as a separate line; they are neither
taxed nor discounted. A suspended customer's invoice carries the suspension note.

## Aging

`aging.py` buckets open receivables by days past due (current, 1-30, 31-60, 61-90, 90+), in
USD at the as-of date's rate.
