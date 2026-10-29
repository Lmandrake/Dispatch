# GL journal and revenue

Each invoice becomes a balanced journal entry: debit receivables (total) and discounts given
(coupons); credit subscription revenue (base lines, per plan), usage revenue (per metric), late
fee income and tax payable. Credit applied adds a second entry moving it from the customer
credit liability to receivables.

## Revenue recognition

Revenue is reported by calendar month in the customer's timezone. Base fees are spread
equally over the days of their segment; `sum` usage in proportion to daily usage; `max` and
`last` usage on the segment's last day. Coupons are spread equally over the period's days. Tax
and late fees are not revenue.
