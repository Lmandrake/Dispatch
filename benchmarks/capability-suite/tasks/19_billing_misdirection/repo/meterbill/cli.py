"""Command line: ``python -m meterbill <command> ...``

    invoice DATA_DIR CYCLE [--customer ID] [--format text|csv|json|html] [--out DIR]
    recon   DATA_DIR CYCLE
    dunning DATA_DIR CYCLE
    rate    DATA_DIR PLAN METRIC QUANTITY
    usage   DATA_DIR CYCLE CUSTOMER
    check   DATA_DIR CYCLE
    aging   DATA_DIR YYYY-MM-DD
    quote   DATA_DIR CURRENCY METRIC=QTY ...
    journal DATA_DIR CYCLE
    revenue DATA_DIR CYCLE CUSTOMER
    statement DATA_DIR CYCLE CUSTOMER
    export  DATA_DIR CYCLE OUT_DIR
    explain DATA_DIR CYCLE CUSTOMER [--line N]

``invoice`` without --out prints the invoices to stdout separated by a form
feed line; with --out it writes ``<number>.<ext>`` files into DIR.
"""

import argparse
import sys
from pathlib import Path

from .errors import BillingError
from .pipeline import dunning_as_of, run_billing
from .reconcile import render_recon
from .render import render

EXT = {"text": "txt", "csv": "csv", "json": "json", "html": "html"}


def _parser():
    p = argparse.ArgumentParser(prog="meterbill", description="usage-based billing")
    sub = p.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("invoice", help="build invoices for a cycle")
    inv.add_argument("data")
    inv.add_argument("cycle")
    inv.add_argument("--customer", action="append")
    inv.add_argument("--format", choices=sorted(EXT), default="text")
    inv.add_argument("--out")
    rec = sub.add_parser("recon", help="reconciliation report")
    rec.add_argument("data")
    rec.add_argument("cycle")
    dun = sub.add_parser("dunning", help="overdue invoices and dunning steps")
    dun.add_argument("data")
    dun.add_argument("cycle")
    rt = sub.add_parser("rate", help="rate a quantity under a plan's charge")
    rt.add_argument("data")
    rt.add_argument("plan")
    rt.add_argument("metric")
    rt.add_argument("quantity")
    us = sub.add_parser("usage", help="daily usage of one customer")
    us.add_argument("data")
    us.add_argument("cycle")
    us.add_argument("customer")
    ck = sub.add_parser("check", help="lint a data directory")
    ck.add_argument("data")
    ck.add_argument("cycle")
    ag = sub.add_parser("aging", help="AR aging")
    ag.add_argument("data")
    ag.add_argument("as_of")
    qt = sub.add_parser("quote", help="compare plans for expected usage")
    qt.add_argument("data")
    qt.add_argument("currency")
    qt.add_argument("usage", nargs="*")
    qt.add_argument("--on", help="rate date (default: today)")
    jn = sub.add_parser("journal", help="GL journal CSV for a cycle")
    jn.add_argument("data")
    jn.add_argument("cycle")
    rv = sub.add_parser("revenue", help="revenue schedule of one invoice")
    rv.add_argument("data")
    rv.add_argument("cycle")
    rv.add_argument("customer")
    sm = sub.add_parser("statement", help="account statement of one customer")
    sm.add_argument("data")
    sm.add_argument("cycle")
    sm.add_argument("customer")
    ex = sub.add_parser("export", help="write a whole run to a directory")
    ex.add_argument("data")
    ex.add_argument("cycle")
    ex.add_argument("out")
    xp = sub.add_parser("explain", help="explain how invoice lines were computed")
    xp.add_argument("data")
    xp.add_argument("cycle")
    xp.add_argument("customer")
    xp.add_argument("--line", type=int, help="1-based line number (default: all)")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "invoice":
            run = run_billing(args.data, args.cycle, customers=args.customer)
            if args.out:
                out = Path(args.out)
                out.mkdir(parents=True, exist_ok=True)
                for inv in run.invoices:
                    (out / f"{inv.number}.{EXT[args.format]}").write_text(render(inv, args.format), encoding="utf-8")
                print(f"wrote {len(run.invoices)} invoice(s) to {out}")
            else:
                sys.stdout.write("\f\n".join(render(inv, args.format) for inv in run.invoices))
        elif args.cmd == "recon":
            run = run_billing(args.data, args.cycle)
            sys.stdout.write(render_recon(args.cycle, run.reconciliation(), run.ingested))
        elif args.cmd == "dunning":
            from .config import load_dataset
            from .dunning import evaluate, render_dunning
            ds = load_dataset(args.data)
            from .periods import prev_cycle
            states = evaluate(ds.receivables, ds.schedule, dunning_as_of(ds, args.cycle), ds.converter(),
                              since=dunning_as_of(ds, prev_cycle(args.cycle)))
            sys.stdout.write(render_dunning(states))
        elif args.cmd == "rate":
            from .config import load_dataset
            from .pricing import fmt_qty
            ds = load_dataset(args.data)
            plan = ds.catalog.plan(args.plan)
            rating = plan.rate(args.metric, args.quantity)
            if rating is None:
                raise BillingError(f"plan {args.plan} has no {args.metric} charge")
            for s in rating.slices:
                print(f"{s.label or args.metric:<24}{fmt_qty(s.quantity):>14} @ {s.unit_price:<12}{s.amount:>16}")
            print(f"{'total':<24}{fmt_qty(rating.chargeable):>14}   {'':<12}{rating.amount:>16} {plan.currency}")
        elif args.cmd == "usage":
            from .usage_report import render_usage
            run = run_billing(args.data, args.cycle, customers=[args.customer.upper()])
            cust = run.dataset.customers.get(args.customer.upper())
            sys.stdout.write(render_usage(cust, args.cycle, run.ingested.records, list(run.dataset.catalog.metrics)))
        elif args.cmd == "check":
            from .config import load_dataset
            from .lint import lint
            from .meters.ingest import load_feeds
            ds = load_dataset(args.data)
            ing = load_feeds(ds.feeds_dir, customers=ds.customers, metrics=ds.catalog.metrics)
            warnings = lint(ds, args.cycle, ing)
            for w in warnings:
                print(f"warning: {w}")
            print(f"{len(warnings)} warning(s)")
        elif args.cmd == "aging":
            from .aging import aging, render_aging
            from .config import load_dataset
            from .timeutil import parse_date
            ds = load_dataset(args.data)
            day = parse_date(args.as_of)
            sys.stdout.write(render_aging(aging(ds.receivables, day, ds.converter()), day))
        elif args.cmd == "quote":
            from datetime import date
            from .config import load_dataset
            from .quotes import compare, render_compare
            from .timeutil import parse_date
            ds = load_dataset(args.data)
            usage = {}
            for item in args.usage:
                k, sep, v = item.partition("=")
                if not sep:
                    raise BillingError(f"expected METRIC=QTY, got {item!r}")
                ds.catalog.metrics.get(k)
                usage[k] = v
            on = parse_date(args.on) if args.on else date.today()
            sys.stdout.write(render_compare(compare(ds.catalog, usage, args.currency.upper(), ds.converter(), on)))
        elif args.cmd == "journal":
            from .ledger import journal, render_journal_csv
            run = run_billing(args.data, args.cycle)
            sys.stdout.write(render_journal_csv(journal(run.invoices)))
        elif args.cmd == "revenue":
            from .revenue import render_schedule, schedule
            run = run_billing(args.data, args.cycle, customers=[args.customer.upper()])
            inv = run.invoice(args.customer.upper())
            sys.stdout.write(render_schedule(inv, schedule(inv, run.ingested.records, run.dataset.catalog)))
        elif args.cmd == "statement":
            from .statements import render_statement, statement
            run = run_billing(args.data, args.cycle, customers=[args.customer.upper()])
            inv = run.invoice(args.customer.upper())
            sys.stdout.write(render_statement(statement(inv.customer, run.dataset.receivables, inv, run.converter)))
        elif args.cmd == "export":
            from .export import export_run
            run = run_billing(args.data, args.cycle)
            m = export_run(run, args.out)
            print(f"exported {len(m['files'])} file(s) to {args.out}")
        elif args.cmd == "explain":
            from .dunning import late_fees_by_customer
            from .explain import explain_invoice, explain_line
            from .invoice import BillingContext
            run = run_billing(args.data, args.cycle, customers=[args.customer.upper()])
            ds = run.dataset
            ctx = BillingContext(catalog=ds.catalog, subscriptions=ds.subscriptions, tax=ds.tax,
                                 converter=run.converter, coupons=ds.coupons, redemptions=ds.redemptions,
                                 grants=ds.grants, late_fees=late_fees_by_customer(run.dunning))
            inv = run.invoice(args.customer.upper())
            if args.line:
                sys.stdout.write(explain_line(ctx, inv, run.ingested.records, args.line - 1).render())
            else:
                sys.stdout.write(explain_invoice(ctx, inv, run.ingested.records))
    except BillingError as e:
        print(f"meterbill: error: {e}", file=sys.stderr)
        return 2
    return 0
