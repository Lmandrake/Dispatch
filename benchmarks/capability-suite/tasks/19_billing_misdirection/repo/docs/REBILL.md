# Re-billing issued invoices

Invoices that were already sent are never edited (docs/INVOICES.md, "Corrections"). When the
engine is corrected, Finance re-bills: every issued invoice is recomputed with the current
engine and the difference is settled with a credit note (the customer was overcharged) or a
debit note (undercharged).

## Input

`<data dir>/issued/` holds the invoices exactly as they were sent, one JSON file per invoice
in the portal format (`render/json_out.py`), named `<invoice number>.json`. Each one gives the
customer, the cycle (`period.cycle`) and the figures that were billed.

Recomputing an issued invoice means building the invoice of that customer for that cycle
from the data directory, exactly as `invoice` would (same feeds, rates, subscriptions,
coupons, credits and dunning for that cycle). The currency must be the one issued; otherwise
it is an error.

## The figures compared

Seven figures, in this order: `subtotal`, `discount` (sum of the coupons, a positive amount),
`tax`, `late_fees`, `total`, `credit` (prepaid credit applied, positive) and `due` (amount
due). For each, `change = corrected - issued`.

The adjustment's own change is the change of `total`, or, when `total` did not change, the
change of `due` (a credit applied wrongly changes only what is due). A negative change is a
credit note, a positive one a debit note; zero means no note.
Note numbers: `CN-<invoice number>` and `DN-<invoice number>`.

The issued figures are read from the issued JSON: `subtotal`, `tax.amount`, `late_fees`,
`total` and `amount_due` (for `due`) directly; `discount` is the sum of `discounts[].amount`
and `credit` the sum of `credits[].applied` (zero when the lists are empty).

Adjustments are ordered by customer id, then cycle, then invoice number.

## API

`meterbill.rebill.rebill(data_dir, *, cycles=None)` returns a list of `Adjustment` (one per
issued invoice, including unchanged ones; `cycles` restricts to those cycles), each with
`issued`, an object with attributes `number`, `customer` (the customer id), `customer_name`,
`cycle`, `currency` and `figures` (a dict with the same seven keys as `corrected`, holding
`Money` in the issued currency); `corrected`
(a dict of the seven figures as `Money`), `change` (`Money`, as defined above), `kind`
(`"credit"`, `"debit"` or `"none"`), `note_number` (`""` for none) and `deltas()` (a dict of
the seven changes).
`render_rebill_text(adjustments)` and `render_rebill_csv(adjustments)` return the two report
formats below. The command line is

    python3 -m meterbill rebill DATA_DIR [--cycle YYYY-MM ...] [--format text|csv]

`--cycle` may be repeated; `--format` defaults to `text`. The command writes the report to
stdout exactly as the render function returns it, adding nothing.

## Text format

Amounts are formatted like invoice amounts (`render/fmt.py` `format_amount`: grouping,
the currency's decimals). A change is printed with a leading `+` when positive, `-` when
negative, and without a sign when zero.

    REBILL ADJUSTMENTS
    ========================================================================   (72 '=')

then, for every adjustment that has a note, in order:

    CREDIT NOTE CN-KC-2026-02-C04              (or DEBIT NOTE DN-...)
      Dunmore Ltd (C04), cycle 2026-02, GBP
      <12 spaces><'issued' right-aligned in 16><'corrected' in 16><'change' in 16>
      <label left-aligned in 12><issued in 16><corrected in 16><change in 16>   x7
    ------------------------------------------------------------------------   (72 '-')

Every row of the note is indented by two spaces. The labels are `subtotal`, `discount`,
`tax`, `late fees`, `total`, `credit`, `amount due`. After the notes:

    SUMMARY
      <customer id left-aligned in 8><invoice count right-aligned in 3> invoice(s)<note count right-aligned in 3> note(s)   net <net change in 14> <currency>
    ...one line per customer that has issued invoices, by id...
      unchanged: <comma-space separated numbers of the invoices without a note, in adjustment order, or ->

`net change` is the sum of that customer's adjustment changes, signed like a change. The report
ends with a newline.

## CSV format

Header `note,kind,invoice,customer,cycle,currency,field,issued,corrected,change`, then seven
rows (one per figure, `field` being the API name: `subtotal` ... `late_fees`, `total`, `credit`, `due`, in the order above) for every adjustment that has a note, in adjustment
order. `kind` is `credit` or `debit`; amounts are plain (`render/fmt.py` `plain_amount`: no
grouping, the currency's decimals, `-` for negatives, no `+`). LF line ends; unchanged
invoices do not appear.
