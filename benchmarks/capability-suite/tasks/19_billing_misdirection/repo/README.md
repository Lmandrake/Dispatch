# meterbill

Usage-based billing for Kettle Cloud: metering feeds in, signed-off invoices out.

    python3 -m meterbill invoice data/mar2026 2026-03                  # every invoice, text
    python3 -m meterbill invoice data/mar2026 2026-03 --customer C09 --format json
    python3 -m meterbill recon   data/mar2026 2026-03                  # month-end reconciliation
    python3 -m meterbill rate    data/mar2026 team api_calls 2500000   # how a quantity is rated
    python3 -m meterbill usage   data/mar2026 2026-03 C02              # daily usage of one customer
    python3 -m meterbill check   data/mar2026 2026-03                  # data lint
    python3 -m meterbill journal data/mar2026 2026-03                  # GL journal
    python3 -m meterbill export  data/mar2026 2026-03 OUT_DIR          # the whole run, with a manifest
    python3 -m meterbill explain data/mar2026 2026-03 C09 --line 4     # how one line was computed

Run the tests with `python3 -m pytest -q`.

## Layout

| module | what it does | rules |
|---|---|---|
| `meters/` | read the gateway CSV, storage JSON-lines and seat log feeds; de-duplicate | docs/METERING.md |
| `timeutil.py`, `periods.py` | timestamps; billing periods in the customer's timezone | docs/PERIODS.md |
| `catalog.py`, `metrics.py`, `pricing.py` | plans, metrics, the five pricing models | docs/PRICING.md |
| `subscriptions.py`, `proration.py` | plan history; prorated base fees | docs/SUBSCRIPTIONS.md |
| `usage.py` | usage records to periods and plan segments | docs/PERIODS.md |
| `discounts.py`, `credits.py` | coupons; prepaid credit | docs/DISCOUNTS.md |
| `fx.py` | exchange rates and conversion | docs/FX.md |
| `tax.py` | tax by jurisdiction | docs/TAX.md |
| `invoice.py`, `numbering.py` | putting an invoice together | docs/INVOICES.md |
| `render/` | text, CSV and JSON invoices | docs/INVOICES.md |
| `dunning.py`, `aging.py`, `statements.py` | overdue invoices | docs/DUNNING.md |
| `reconcile.py` | the reconciliation report | docs/RECONCILIATION.md |
| `ledger.py`, `revenue.py`, `credit_notes.py` | GL journal, revenue schedule, corrections | docs/LEDGER.md |
| `quotes.py`, `alerts.py`, `usage_report.py`, `lint.py`, `export.py` | sales quotes, usage alerts, reports, lint, export | |

## Golden invoices

`tests/golden/mar2026/` holds the March 2026 invoices and the reconciliation report exactly as
Finance signed them off (sign-off sheet FIN-2026-041, 2026-04-30). They were produced by hand
in the billing spreadsheet from the same data in `data/mar2026/`, following the rules in `docs/`.
`tests/test_golden.py` compares the program's output with them byte for byte. They are the
specification; do not regenerate them from the program.
