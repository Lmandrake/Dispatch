# Restatement

A rebill (docs/REBILL.md) corrects invoices one at a time. A **restatement** re-runs a whole
window of cycles, oldest first, with the current engine, and carries the consequences of each
correction into the following cycles: an overcharge on a paid invoice becomes account credit
that the next invoices consume, a corrected unpaid invoice changes the balance that dunning
sees, and late fees follow the corrected balances. Finance uses the journal and the revenue
schedule it produces to restate the books.

All amounts are `Money`; nothing in a restatement rounds except where this document says so.

## Inputs

The data directory as for billing, plus `issued/` (docs/REBILL.md) and `receivables.csv`,
which lists every issued invoice with its due date and, if it was paid, the payment date.

## The window and the restatement date

`first` and `last` are cycles (`YYYY-MM`); the window is every cycle from `first` to `last`
inclusive; `restate` raises `meterbill.errors.BillingError` when `last` is before `first`. The **restatement date** is the day after
the latest issue date of the cycle `last` over *all* customers in customers.csv (whatever their
status); a customer's issue date for a cycle is the day after the last day of its billing
period for that cycle (`numbering.issue_date`, the `issued` field of an invoice).

## State carried from cycle to cycle

The restatement keeps two lists that start from the data files and change as it goes:

* the **grants**: credits.csv, in file order;
* the **receivables**: receivables.csv.

## One cycle

For each cycle of the window, in order:

1. **Dunning.** When the data has a dunning schedule and the receivables list is not empty,
   evaluate dunning on the current receivables exactly as a normal billing run does (on the
   cycle's dunning date, with the previous cycle's dunning date as the already-billed limit;
   docs/DUNNING.md). For the first cycle of the window the previous cycle is the cycle before
   `first`, its dunning date computed from the data directory as usual. Its late fees and suspensions apply to this cycle's invoices.
2. **Invoices.** Build the invoice of every customer billed in the cycle (docs/SUBSCRIPTIONS.md,
   closed customers), in customer id order, exactly as `invoice` would, except that the
   credits available are the current grants list.
3. **Credit balances.** For every credit use with a non-zero applied amount on these invoices,
   the grant's amount becomes the use's remaining balance (`CreditUse.remaining`); a grant
   whose balance becomes zero is removed from the list. Order is kept.
4. **Corrections.** For every invoice of step 2 that was issued (a file with its number in
   `issued/`), in invoice order:
   * if the receivables list has an **unpaid** entry with that number (`paid_on` empty), the
     entry's amount becomes the corrected amount due; when that changes the amount, the
     change is recorded as a *receivable change* `(number, old amount, new amount)`;
   * otherwise (the invoice was paid, or was never a receivable), if the issued amount due is
     larger than the corrected amount due, the difference becomes a new grant, a
     **restatement credit**: grant id `RS-<invoice number>`, the invoice's customer and
     currency, `granted` = the corrected invoice's issue date, `expires` = 90 days after
     that, appended at the end of the grants list. An undercharge on a paid invoice creates
     nothing here; it is collected through rebill.

   Invoices that were never issued are not added to the receivables. After the step the
   receivables list is ordered by (due date, invoice number).
5. **Journal** and 6. **Revenue**, below.

A restatement credit follows every normal credit rule (docs/DISCOUNTS.md): it is usable on
invoices issued on or after its `granted` day and before its `expires` day, and grants are used
soonest-expiring first, then by grant id.

## The journal

Journal entries of a cycle, in this order:

1. for each invoice of the cycle, in invoice order:
   * if the invoice was issued: the **reversal** of the issued invoice (refs `REV-<number>`
     and, if it applied credit, `REV-<number>/CR`), dated the restatement date;
   * the corrected invoice's entries (refs `<number>` and, if it applies credit,
     `<number>/CR`), dated the invoice's issue date;
2. for each receivable change, in order, entry `AR-<number>`, dated the restatement date;
3. for each restatement credit created in the cycle, in order, an entry whose ref is the grant
   id, dated the restatement date.

An **invoice's entries** are computed from its figures as printed in the portal JSON
(`render/json_out.py`), which for an issued invoice is the file in `issued/`:

* entry `<number>`, postings in this order:
  1. debit `1200` the total, memo the customer id;
  2. debit `4900` each coupon's amount, in invoice order, memo the coupon code;
  3. credit `4100` the base-line amounts summed per plan, plans in order of first appearance
     on the invoice, memo the plan id;
  4. credit `4200` the usage-line amounts summed per metric, metrics sorted by id, memo the
     metric id;
  5. credit `4300` the sum of the fee lines, memo `late fees`;
  6. credit `2300` the tax, memo the tax jurisdiction code;
* entry `<number>/CR`, only when credit was applied: for each credit use with a non-zero applied
  amount, in order, a debit of the applied amount to `2410` if the grant id starts with `RS-`,
  otherwise to `2400`, memo the grant id; then one credit to `1200` of the total applied, memo
  the customer id.

A **reversal** has the same postings in the same order with debit and credit swapped.

`AR-<number>`, with `d = new - old`: when `d` is negative, debit `4950` and credit `1200` by
`-d`; when positive, debit `1200` and credit `4950` by `d`; memo the customer id on both.

A restatement credit's entry: debit `4950`, credit `2410`, both of the grant amount, memo the
customer id.

Postings of zero are left out (an entry never has a zero posting). Every entry balances.

Account names:

| account | name |
|---|---|
| 1200 | Accounts receivable |
| 2300 | Tax payable |
| 2400 | Customer credit liability |
| 2410 | Restatement credit liability |
| 4100 | Subscription revenue |
| 4200 | Usage revenue |
| 4300 | Late fee income |
| 4900 | Discounts given |
| 4950 | Billing corrections |

## The revenue schedule

Revenue of the corrected invoices, per customer and local calendar day:

* a **base line** is recognised ratably: its amount is split equally over the local days of its
  segment (`money.allocate` with equal weights: largest remainder, the minor units that do not
  divide evenly going to the earliest days);
* a **usage line** is recognised at a point in time: its whole amount on the last day of its
  segment (the line's `end` minus one day; `end` is exclusive);
* fee lines and zero lines are not revenue; tax is not revenue;
* each coupon is negative revenue, split equally over the days of the invoice's billing period
  the same way.

The schedule of a cycle sums these per (customer, day) over the cycle's invoices; days whose
sum is zero are left out.

## API

    from meterbill.restatement import restate, render_summary, render_journal, render_revenue
    res = restate(data_dir, first, last)

`res.first`, `res.last`, `res.on` (the restatement date), `res.cycles` (one per cycle, in
order), `res.grants` (the grants list after the last cycle) and `res.receivables` (the
receivables list after the last cycle, as `dunning.Receivable`, in (due date, invoice number)
order). Each cycle has `cycle`,
`invoices` (the corrected `Invoice` objects, in customer id order), `issued` (a dict invoice
number -> issued invoice, for those that were issued), `grants_created` (the restatement
credits, as `credits.Grant`), `receivable_changes` (a list of `(number, old Money, new
Money)`), `journal` (the entries, `ledger.JournalEntry`) and `revenue` (a dict `(customer id,
"YYYY-MM-DD")` -> `Money`).

`res.cycle("YYYY-MM")` returns that cycle's entry and `res.invoice(number)` the corrected
`Invoice` with that number from any cycle; both raise `KeyError` when there is none.

Command line:

    python3 -m meterbill restate DATA_DIR FIRST LAST [--report summary|journal|revenue]

`--report` defaults to `summary`; the command writes the report to stdout exactly as the
render function returns it.

## Report formats

Amounts in the summary use `format_amount` (grouping, the currency's decimals); in the two
CSVs `plain_amount`. CSVs have LF line ends.

### Journal (`render_journal`)

Header `cycle,ref,line,date,account,account_name,debit,credit,currency,memo`; one row per
posting, entries in journal order, `line` numbering the postings of an entry from 1. `debit`
or `credit` is empty on the side that is not used.

### Revenue (`render_revenue`)

Header `cycle,customer,day,amount,currency`; rows by cycle in window order, then customer id,
then day.

### Summary (`render_summary`)

    RESTATEMENT <first> to <last> (as of <restatement date>)
    ========================================================================   (72 '=')

then for each cycle:

    CYCLE <cycle>
      <'invoice' left in 20><'issued due' right in 16><'restated due' right in 16><'change' right in 16>
      <number left in 20><issued due in 16><restated due in 16><change in 16>      one per invoice

For an invoice that was not issued, the issued due is `-` and the change is `new`. A change is
the restated minus the issued amount due, with a leading `+` when positive. After the
invoices, each indented by two spaces:

    receivable <number>: <old> -> <new> <currency>               per receivable change
    credit <grant id>: <amount> <currency>, usable <granted> to <expires>    per restatement credit
    late fees on <number>: <late fees> <currency>                per invoice with late fees

then a line of 72 `-`. After the last cycle:

    OPEN CREDITS
      <customer id left in 8><grant id left in 22><balance right in 14> <currency>  expires <expires or never>

listing the grants after the last cycle that have a balance and have not expired on the
restatement date (`expires` empty or after it), ordered by customer id then grant id, or a
single `  -` when there are none. The report ends with a newline.
