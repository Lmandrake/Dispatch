# Month-end close: entities, consolidation, revaluation and the audit pack

The month-end close runs after a restatement (docs/RESTATEMENT.md) and turns its corrected
invoices into the group's books. It is implemented in the package `meterbill.close`
(`meterbill/close/`), with the command

    python3 -m meterbill close DATA_DIR FIRST LAST [--report NAME] [--out DIR]

All amounts are `Money`. Nothing rounds except where this document says so; every rounding is
half-up to the minor unit of the currency named.

## 1. Entities

Kettle Cloud invoices through three legal entities. `entities.toml` in the data directory:

    [entities.KC-US]
    name = "Kettle Cloud Inc."
    functional_currency = "USD"
    currencies = ["USD", "CAD", "JPY", "AUD"]

    [entities.KC-EU]
    name = "Kettle Cloud B.V."
    functional_currency = "EUR"
    currencies = ["EUR", "CHF", "SEK"]

    [entities.KC-UK]
    name = "Kettle Cloud Ltd"
    functional_currency = "GBP"
    currencies = ["GBP"]

    [group]
    presentation_currency = "USD"
    parent = "KC-US"

An invoice belongs to the entity whose `currencies` list contains the **invoice currency**; a
currency in no list or in two lists is a configuration error (`ConfigError`) raised when the
file is loaded. Entity codes are sorted alphabetically wherever entities are listed. A missing
`entities.toml` is an error for `close` (and for nothing else).

## 2. Inputs

`close(data_dir, first, last)`:

1. runs `restate(data_dir, first, last)` (docs/RESTATEMENT.md) and works on its result: the
   corrected invoices of every cycle, the journal entries of every cycle, the receivables after
   the last cycle (`res.receivables`, see below) and the restatement date `res.on`;
2. reads `entities.toml` and `payments.csv` (`meterbill.payments`: payment id, customer,
   currency, amount, received date, reference). A missing `payments.csv` means no payments.

`Restatement.receivables` is the corrected receivables list after the last cycle (step 4 of
"One cycle" in docs/RESTATEMENT.md), in (due date, invoice number) order.

### Month-ends

For each cycle `YYYY-MM` of the window, the **month-end** is the last calendar day of that
month (2026-01-31, 2026-02-28, ...), and the **reversal day** is the day after it.

## 3. Open receivables at a month-end

An entity's open receivables at month-end `M` are, from the receivables list of step 2 plus
every corrected invoice of the window with a non-zero amount due that is not in that list
(numbers not in receivables.csv: invoices first billed by the restatement):

* the receivable's issue date is on or before `M` (the issue date of an invoice is the day
  after its billing period, docs/PERIODS.md; for a receivable that is not an invoice of the
  window, its due date minus 30 days);
* it is not paid on or before `M` (`paid_on` empty or after `M`);
* its open amount on `M` is what `meterbill.payments.allocate_payments` leaves outstanding
  when it is given the receivables that pass the two tests above, each with its `paid_on`
  cleared (a payment recorded after `M` has not happened yet on `M`), and the payments received
  on or before `M`; a receivable whose open amount is zero is not open.

The allocation result of a month-end is also used by the cash tie-out (section 7).

## 4. FX revaluation

At every month-end each entity revalues its open receivables that are not in its functional
currency.

* The **booking rate** of a receivable is the cross rate (fx.py) from its currency to the
  entity's functional currency on the receivable's issue date; its **booked value** is
  `open amount x booking rate`, rounded to the functional currency.
* The **closing rate** is the cross rate on the month-end; the **closing value** is `open
  amount x closing rate`, rounded the same way.
* The **difference** is closing value minus booked value. Differences are summed per entity.

Revaluation journal, one entry per entity with a non-zero total difference, ref
`FXR-<entity>-<YYYY-MM>`, dated the month-end, in the functional currency:

* a gain (positive total): debit `1210` "Receivables revaluation", credit `7100` "Unrealised FX
  gain/loss";
* a loss (negative total): debit `7100`, credit `1210`, by the absolute value;
* memo `revaluation <YYYY-MM>` on both postings.

Each revaluation entry is reversed on the reversal day by an entry with ref
`FXR-<entity>-<YYYY-MM>/REV`, the same postings in the same order with debit and credit
swapped, dated the reversal day. (The reversal of the last month-end of the window is included.)

## 5. Intercompany

Customers are billed by the entity of their invoice currency, but every invoice's revenue
belongs, for management purposes, to the **servicing entity**: `KC-EU` when the customer's tax
jurisdiction (as resolved by `meterbill.jurisdiction`, docs/TAX.md) is in the EU (`jurisdiction
.is_eu`), `KC-UK` when its country is `GB`, otherwise `KC-US`.

When the invoicing entity and the servicing entity differ, the invoicing entity owes the
servicing entity the invoice's **net revenue** (subtotal minus discount minus late fees, in the
invoice currency) less a 5% service retention, rounded to the invoice currency:

    intercompany charge = round(net revenue x 0.95)

An intercompany charge of zero or less creates nothing. For every other such invoice of the
window, two entries, both dated the invoice's issue date, in the invoice currency, ref
`IC-<invoice number>`:

* in the invoicing entity's books: debit `4800` "Intercompany cost of service", credit `2900`
  "Intercompany payable", memo the servicing entity code;
* in the servicing entity's books, ref `IC-<invoice number>/S`: debit `1900` "Intercompany
  receivable", credit `4810` "Intercompany service revenue", memo the invoicing entity code.

## 6. Consolidation

The group presents in USD. The consolidated books at a month-end are made of every entry
**dated on or before the month-end** from three journals:

1. the restatement journal of every cycle of the window (docs/RESTATEMENT.md; entries dated the
   restatement date fall after every month-end of the window and are therefore not included);
2. the intercompany entries (section 5);
3. the revaluation entries and their reversals (section 4) of this and earlier month-ends (a
   month-end's reversal is dated the next day, so it is not in that month's books).

Each entry is **translated** to USD at the closing rate of the month-end (cross rate from the
entry's currency to USD on the month-end), posting by posting, keeping the posting order:
`round(debit x rate)` and `round(credit x rate)` separately, to USD; a posting that translates
to zero is dropped. When the translated entry no longer balances, one posting to `7200` with
memo `rounding` is appended that balances it (debit when the credits exceed the debits). An
entry already in USD translates to itself.

**Eliminations.** Accounts `1900` and `2900`, and accounts `4800` and `4810`, are intercompany
pairs. On consolidation each pair is eliminated: the consolidated balance of `1900`, `2900`,
`4800` and `4810` is reported as zero, and the difference that remains after translation (the
net of the pair's translated balances, which is not zero when the two sides were translated
from different currencies or rounded differently) goes to `7200` "Translation difference". The
elimination is an entry with ref `ELIM-<YYYY-MM>`, dated the month-end, in USD, with postings in
this order: for `1900`, `2900`, `4800`, `4810` in that order, the posting that brings the
account's translated net balance to zero (net balance = debits - credits; a positive net is
removed with a credit, a negative one with a debit; zero means no posting), then one posting to
`7200` that balances the entry (debit when the entry's credits exceed its debits), memo
`elimination <YYYY-MM>` on all.

The elimination entry is computed from the translated entries of the month-end (before it is
added). The **consolidated trial balance** at a month-end is, for every account that has any
posting in the translated entries or the elimination, the debits and credits summed per account
over the translated entries plus the elimination entry.

## 7. The audit pack

`close` returns a `Close` object (below). `render_pack(close)` returns a dict file name -> text
of the following CSVs (LF line ends, amounts `plain_amount`); `--out DIR` writes them there and
prints `wrote <n> file(s) to <DIR>`, and `--report NAME` prints one of them (NAME without
`.csv`).

### entities.csv

`entity,name,functional_currency,currencies`: one row per entity; `currencies` is the list joined
with `;` in file order.

### revaluation.csv

`month_end,entity,invoice,currency,open_amount,booking_rate,booked,closing_rate,closing,difference`

One row per revalued receivable, by month-end, then entity, then invoice number. Rates are
printed as the Decimal cross rate (10 places, `f` format). `booked`, `closing` and `difference`
are in the entity's functional currency.

### journal.csv

All the close's own entries (not the restatement's, and untranslated: each in its own currency),
header `entity,ref,line,date,account,account_name,debit,credit,currency,memo`, in this order:
first the intercompany entries of the window's invoices in invoice-number order, each `IC-`
entry (entity: the invoicing entity) followed by its `/S` entry (entity: the servicing entity);
then per month-end in window order: its revaluation entries (entities in code order), its
elimination entry (entity `GROUP`), then its revaluation reversals (entities in code order).
`line` numbers the postings of an entry from 1; account names come from the tables in this
document and docs/RESTATEMENT.md.

### trial_balance.csv

`month_end,account,account_name,debit,credit,net` per month-end in window order, then account
(sorted as text), the translated and eliminated USD totals; `net` is debit minus credit. A last
row per month-end with account `TOTAL`, empty account name, the sums of the debit and credit
columns and their net, which must be `0.00`.

### tie_out.csv

`month_end,check,expected,actual,status` per month-end, with these checks in this order:

1. `invoiced_vs_receivable`: the sum over the window's invoices issued on or before the
   month-end of their totals converted to USD at the closing rate and rounded per invoice
   (expected), against the sum of the `1200` debits of the translated invoice entries (the
   restatement's entries whose ref is exactly the number of an invoice of the window) in the
   month-end's books (actual);
2. `revenue_schedule`: the restatement's revenue schedule summed over the days up to and
   including the month-end, converted per (customer, day) to USD at the closing rate and rounded
   (expected), against, over the same translated invoice entries, credits minus debits of
   `4100` and `4200` plus credits minus debits of `4900` (actual);
3. `cash`: the payments received on or before the month-end converted to USD at the closing
   rate and rounded per payment (expected), against the month-end's allocation result: per
   payment id (sorted), its allocated amounts plus its unapplied amount, converted and rounded the
   same way, summed (actual);
4. `trial_balance`: `0.00` (expected) against the trial balance's TOTAL net (actual);
5. `eliminations`: `0.00` against the sum of the consolidated nets of `1900`, `2900`, `4800`
   and `4810` after elimination.

`status` is `ok` when expected equals actual, otherwise `DIFF <actual - expected>`. The
revenue check can legitimately differ (the schedule spreads base fees over days that may fall
after the month-end); every other check must be `ok`.

`tie_out(close)` returns the rows as `(month_end, check, expected Money, actual Money)`
tuples. `assert_tied(close)` raises `TieOutError` (`meterbill.close.TieOutError`, a
`BillingError`) naming every failing check other than `revenue_schedule`; `close` calls it, so
a close that does not tie never returns. `python3 -m meterbill close` exits with status 2 and
prints `meterbill: error: tie-out failed: <check> <month_end>; ...` on stderr in that case.

## 8. API

    from meterbill.close import close, render_pack, tie_out, assert_tied, TieOutError, load_entities

* `load_entities(text)` parses `entities.toml` into an `Entities` object with `entities` (a
  dict code -> `Entity(code, name, functional_currency, currencies)` in code order),
  `presentation_currency`, `parent` and `entity_for(currency)`.
* `close(data_dir, first, last)` returns `Close` with `restatement`, `entities`, `month_ends`
  (list of dates), `revaluation` (a list of `RevaluationRow(month_end, entity, invoice,
  currency, open_amount, booking_rate, booked, closing_rate, closing, difference)`),
  `entries` (the close's own `ledger.JournalEntry` objects in journal.csv order, each with an
  extra attribute `entity`), and `trial_balance` (a dict month_end date -> dict account ->
  `Money` net, USD, without the `TOTAL` row).
* `render_pack(close)` returns {"entities.csv", "revaluation.csv", "journal.csv",
  "trial_balance.csv", "tie_out.csv"} -> text.

Account names, in addition to docs/RESTATEMENT.md:

| account | name |
|---|---|
| 1210 | Receivables revaluation |
| 1900 | Intercompany receivable |
| 2900 | Intercompany payable |
| 4800 | Intercompany cost of service |
| 4810 | Intercompany service revenue |
| 7100 | Unrealised FX gain/loss |
| 7200 | Translation difference |
