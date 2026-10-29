# Subscriptions and proration

`subscriptions.csv` rows (`customer,plan,effective`) say that from local calendar day
`effective` (inclusive) the customer is on `plan`. Plan `none` ends the subscription. Rows can
be in any order. A customer cannot switch to a plan marked `legacy`. A row that repeats the
current plan is allowed and does not split anything.

When two rows of one customer have the same effective day, **the row further down the file
wins** and the other is ignored: Sales Ops corrects a mistaken change by adding the right row
below it, never by editing the old one. The plan ids themselves play no part in the order.

A closed customer (`status = closed`) still gets a final invoice for every cycle in which it
had a plan for at least one day; after that it is not invoiced.

## Proration

The base fee pays for one whole billing period. When a period contains a plan change, it is
split into segments and each segment pays

    base fee of its plan x (days in the segment) / (days in the billing period)

The denominator is the number of local calendar days in **that billing period**, which for an
anchor-15 customer runs from the 15th to the 14th of the next month. It is not the length of
the calendar month in which the segment starts or the change happens, and it is never a
fixed 30. Example: a period of 15 March to 14 April has 31 days; a change on 2 April gives
segments of 18 and 13 days, billed 18/31 and 13/31.

The fraction is exact; the amount is carried at 8 decimal places, converted to the invoice
currency and rounded once, on the invoice line.

Days of a period with no plan (before the first row or after `none`) have no base fee, and
usage on those days is not billed; it is reported as unbilled.
