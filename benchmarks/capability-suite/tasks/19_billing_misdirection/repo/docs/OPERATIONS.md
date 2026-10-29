# Operations modules

Supporting modules for the people who run billing day to day. None of them
changes how an invoice is computed: they read the objects the pipeline
produces (invoices, dunning states, ingested records, the catalogue) and
present, group or export them. All money is `Decimal`/`Money`; none of these
modules rounds, converts or re-rates anything itself.

## Payments (`meterbill/payments.py`)

`data/payments.csv` has `payment_id,customer,currency,amount,received,reference`.
`parse_payments` rejects duplicate ids, non-positive amounts, amounts finer than
the currency's minor unit and bad dates (`ConfigError`).

`allocate_payments(receivables, payments)`:

1. payments in order of received date, then id;
2. each goes to the customer's open receivables of the same currency, oldest
   due date first (ties: invoice number); receivables already carrying `paid_on`
   take nothing;
3. a payment smaller than the open amount is a partial allocation, a larger
   one leaves *unapplied cash*;
4. no currency conversion: a payment in a currency with no open receivable is
   unapplied in full.

`render_allocation_report` prints one row per receivable (state `open`,
`partial`, `settled` or `paid`), then the allocations and the unapplied cash.

## Notifications (`meterbill/notifications.py`)

Plain-text e-mail bodies from string templates (`TEMPLATES`), wrapped at 72
columns: `invoice_issued(invoice)`, `payment_reminder(state, customer)`,
`suspension_notice(state, customer)`, `usage_alert(fired, customer, metrics)`.
Each returns a `Notification(to, subject, body)`; `.render()` adds headers.
Output is deterministic. `notifications_for_run(run)` builds every invoice
and dunning notice of a billing run for customers that have an e-mail
address. Reminders and suspension notices raise `ValueError` when the state
has not reached the relevant step.

## Customer portal (`meterbill/portal/`)

`handle(path, query, run) -> (status, dict)` is a pure function over a
`BillingRun`; no server is included.

| path | answer |
|---|---|
| `/customers`, `/customers/<id>` | customer documents (ids case-insensitive) |
| `/customers/<id>/invoices` | that customer's invoice summaries |
| `/customers/<id>/usage` | per-metric billed quantity of the run's period |
| `/invoices/<number>` | the full invoice |
| `/plans`, `/plans/<id>` | catalogue (`?legacy=1` includes legacy plans) |

Amounts are strings (`"1234.50"`, plain machine form), dates ISO, keys always
present. List endpoints take `limit` (1-100, default 25) and `cursor` (the
`next_cursor` of the previous page). Errors are
`{"error": "not_found" | "bad_request", "message": ...}` with status 404 or 400.

## Usage rollups (`meterbill/rollups.py`)

`hourly` and `daily` bucket records by the customer's local hour or date and
combine each bucket with the metric's own aggregation (sum, max, last).
Empty buckets are omitted unless `daily(..., fill_gaps=True)`. Hourly buckets
are keyed by UTC start, so the repeated hour of a fall-back night is two
buckets. `rollups_to_csv` and `render_rollups` export them.

## Feed statistics (`meterbill/feedstats.py`)

`feed_stats(ingested)` gives, per feed file: accepted records, per-metric and
per-customer counts, summed quantities, first and last instant, rejects and a
histogram of reject reasons. Reasons are normalised (`reason_class`) so that
"unknown customer C99" and "unknown customer C12" count together. Replays are
not attributable to a file; only the total is shown.

## Price book (`meterbill/pricebook.py`)

`render_price_book(catalog)` writes each plan with its base fee, allowances
and tiers in words ("first 1,000,000 calls at 0.0004 USD"); `price_book_csv`
writes one row per plan, charge and tier. Prices are never rounded.

## Customer export and diff (`meterbill/customer_io.py`)

`customers_to_csv` writes the columns of `customers.csv` in a stable order,
sorted by id; a re-import gives equal customers. `diff_customers` and
`diff_customer_files` report added, removed and changed customers by field;
`render_diff` prints the audit text. Comparison is on parsed values, so case or
spacing differences normalised by the parser are not reported.

## Plan migration advice (`meterbill/plan_migration.py`)

`recommend(catalog, customer, current_plan, usage, converter, on)` quotes
(through `quotes.compare`) every non-legacy plan priced in the customer's
invoice currency, and recommends the cheapest if it is strictly cheaper than
the current plan, with the saving. A legacy current plan is the baseline but
is never recommended as a move. `render_advice` prints the report. It is a
suggestion: contract terms and notice periods are not considered.
