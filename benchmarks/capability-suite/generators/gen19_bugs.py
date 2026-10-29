"""Task 19 bug injector: BUGS[name] = [(relative file, old, new), ...] applied to a copy of the reference.

No injected text narrates the wrong behaviour.
"""
BUGS = {
 # 1 period end = start + N days (DST)
 "dst": [("meterbill/periods.py",
"""    start_utc = local_midnight(start, tz)
    end_utc = local_midnight(end, tz)
""",
"""    start_utc = local_midnight(start, tz)
    end_utc = start_utc + timedelta(days=(end - start).days)
"""),
  ("meterbill/periods.py", "from datetime import date, datetime\n", "from datetime import date, datetime, timedelta\n")],
 # 2 volume tier bound exclusive
 "tier": [("meterbill/pricing.py",
"""        if tier.up_to is None or quantity <= tier.up_to:""",
"""        if tier.up_to is None or quantity < tier.up_to:""")],
 # 3 proration over the calendar month of the segment start
 "proration": [("meterbill/proration.py",
"""    period_days = period.days
""",
"""    period_days = calendar.monthrange(segment.start.year, segment.start.month)[1]
"""),
  ("meterbill/proration.py", "from dataclasses import dataclass\n", "import calendar\nfrom dataclasses import dataclass\n")],
 # 4 coupons after tax
 "coupon_tax": [("meterbill/invoice.py",
"""    inv.tax = ctx.tax.compute(customer, [ln.amount for ln in taxable_lines], inv.discount_total)
    inv.total = inv.tax.taxable + inv.tax.tax + inv.late_fees
""",
"""    inv.tax = ctx.tax.compute(customer, [ln.amount for ln in taxable_lines], Money.zero(cur))
    inv.total = inv.tax.taxable + inv.tax.tax - inv.discount_total + inv.late_fees
""")],
 # 5 fx memo keyed on dst quote date
 "fx_memo": [("meterbill/fx.py",
"""        key = (src, dst, on)
""",
"""        key = (src, dst, self.table.effective_on(dst, on))
""")],
 # 6 naive CSV split, extra fields skipped
 "csv_comma": [("meterbill/meters/csv_feed.py",
"""def _split_rows(text):
    \"\"\"Yield (line_number, fields, raw_text) for each physical record.\"\"\"
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    lines = text.splitlines(keepends=True)
    prev = 0
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error as e:
            yield reader.line_num, None, f"unparseable CSV: {e}"
            prev = reader.line_num
            continue
        start = prev + 1
        prev = reader.line_num
        yield start, fields, "".join(lines[start - 1:reader.line_num])
""",
"""def _unquote(field):
    if len(field) >= 2 and field[0] == '"' and field[-1] == '"':
        return field[1:-1].replace('""', '"')
    return field


def _split_rows(text):
    \"\"\"Yield (line_number, fields, raw_text) for each line.\"\"\"
    for lineno, line in enumerate(text.splitlines(), start=1):
        yield lineno, [_unquote(f) for f in line.split(",")], line
"""),
  ("meterbill/meters/csv_feed.py",
"""        if len(fields) != len(header):
            result.reject(lineno, f"{len(fields)} fields, expected {len(header)}", raw)
            continue
""",
"""        if len(fields) > len(header):
            continue
        if len(fields) != len(header):
            result.reject(lineno, f"{len(fields)} fields, expected {len(header)}", raw)
            continue
"""),
  ("meterbill/meters/csv_feed.py", "import csv\nimport io\n\n", "")],
 # 7 credit grant usable on its expiry day
 "credit_expiry": [("meterbill/credits.py",
"""        return self.granted <= day and (self.expires is None or day < self.expires)""",
"""        return self.granted <= day and (self.expires is None or day <= self.expires)""")],
 # 8 late fee billed again every cycle
 "late_fee_repeat": [("meterbill/pipeline.py",
"""    return evaluate(ds.receivables, ds.schedule, dunning_as_of(ds, cycle), conv,
                    since=dunning_as_of(ds, prev_cycle(cycle)))""",
"""    return evaluate(ds.receivables, ds.schedule, dunning_as_of(ds, cycle), conv)""")],
 # 9 jurisdiction precedence: billing address before service region
 "juris_order": [("meterbill/jurisdiction.py",
"""PRECEDENCE = ("tax_override", "service_region", "jurisdiction")""",
"""PRECEDENCE = ("tax_override", "jurisdiction", "service_region")""")],
 # 10 JSONL ISO ts: offset dropped (wall clock read as UTC)
 "jsonl_offset": [("meterbill/meters/jsonl_feed.py",
"""    if dt.tzinfo is None:
        raise ValueError(f"ts without an offset: {ts!r}")
    return dt.astimezone(UTC)""",
"""    return dt.replace(tzinfo=UTC)""")],
 # 11 dedup only within one feed file
 "dedup_scope": [("meterbill/meters/ingest.py",
"""    seen = {}
    for res in results:
        out.files.append(res.source)""",
"""    for res in results:
        seen = {}
        out.files.append(res.source)""")],
 # 12 same-day plan changes: ordered by plan id
 "same_day": [("meterbill/subscriptions.py",
"""            lst.sort(key=lambda c: c.effective)
            collapsed = []""",
"""            lst.sort(key=lambda c: (c.effective, c.plan))
            collapsed = []""")],
 # 13 closed customers get no final invoice
 "closed_final": [("meterbill/pipeline.py",
"""    if cust.billable:
        return True
    period = billing_period(cycle, cust.anchor_day, cust.timezone)
    return bool(ds.subscriptions.segments(cust.id, period))""",
"""    return cust.billable""")],
 # 14 chain: instant memo keyed on wall clock only (ingestion -> segment -> pricing)
 "instant_memo": [("meterbill/timeutil.py",
"""    key = m.groups()
""",
"""    key = s[:19]
""")],
 # 15 chain: allocation weights truncated (money -> per-line tax / revenue)
 "alloc_weight": [("meterbill/money.py",
"""    \"\"\"A share weight as a Decimal; only the ratios between weights matter.\"\"\"
    return dec(w)""",
"""    \"\"\"A share weight as a Decimal; only the ratios between weights matter.\"\"\"
    return dec(w).to_integral_value(rounding=ROUND_DOWN)""")],
 # 16 chain: proration rounded to cents in plan currency (proration -> FX -> invoice line)
 "prorate_round": [("meterbill/proration.py",
"""    amount = precise(Decimal(base_fee) * frac.numerator / frac.denominator)""",
"""    amount = precise(Decimal(base_fee) * frac.numerator / frac.denominator).quantize(Decimal("0.01"))""")],
}

import shutil, sys
from pathlib import Path


STRIP = [("meterbill/cli.py", """    rebill  DATA_DIR [--cycle CYCLE] [--format text|csv]
""", ""),
 ("meterbill/cli.py", """    rb = sub.add_parser("rebill", help="credit/debit notes for issued invoices")
    rb.add_argument("data")
    rb.add_argument("--cycle", action="append")
    rb.add_argument("--format", choices=("text", "csv"), default="text")
""", ""),
 ("meterbill/cli.py", """        elif args.cmd == "rebill":
            from .rebill import rebill, render_rebill_csv, render_rebill_text
            adj = rebill(args.data, cycles=args.cycle)
            sys.stdout.write(render_rebill_text(adj) if args.format == "text" else render_rebill_csv(adj))
""", ""),
 ("meterbill/cli.py", """    restate DATA_DIR FIRST LAST [--report summary|journal|revenue]
""", ""),
 ("meterbill/cli.py", """    rs = sub.add_parser("restate", help="restate a window of past cycles")
    rs.add_argument("data")
    rs.add_argument("first")
    rs.add_argument("last")
    rs.add_argument("--report", choices=("summary", "journal", "revenue"), default="summary")
""", ""),
 ("meterbill/cli.py", """        elif args.cmd == "restate":
            from .restatement import render_journal, render_revenue, render_summary, restate
            res = restate(args.data, args.first, args.last)
            sys.stdout.write({"summary": render_summary, "journal": render_journal,
                              "revenue": render_revenue}[args.report](res))
""", ""),
 ("meterbill/cli.py", """    close   DATA_DIR FIRST LAST [--report NAME] [--out DIR]
""", ""),
 ("meterbill/cli.py", """    cl = sub.add_parser("close", help="month-end close and audit pack")
    cl.add_argument("data")
    cl.add_argument("first")
    cl.add_argument("last")
    cl.add_argument("--report", choices=("entities", "revaluation", "journal", "trial_balance", "tie_out"))
    cl.add_argument("--out")
""", ""),
 ("meterbill/cli.py", """        elif args.cmd == "close":
            from .close import close, render_pack
            pack = render_pack(close(args.data, args.first, args.last))
            if args.out:
                out = Path(args.out)
                out.mkdir(parents=True, exist_ok=True)
                for name, text in pack.items():
                    (out / name).write_text(text, encoding="utf-8")
                print(f"wrote {len(pack)} file(s) to {out}")
            else:
                sys.stdout.write(pack[f"{args.report or 'tie_out'}.csv"])
""", "")]


def strip_stage2(root):
    root = Path(root).resolve()
    (root / "meterbill/rebill.py").unlink()
    (root / "meterbill/restatement.py").unlink()
    shutil.rmtree(root / "meterbill/close")
    for rel, old, new in STRIP:
        p = root / rel
        s = p.read_text()
        assert s.count(old) == 1, rel
        p.write_text(s.replace(old, new))


def apply(root, names):
    root = Path(root)
    for n in names:
        for rel, old, new in BUGS[n]:
            p = root / rel
            s = p.read_text()
            assert s.count(old) == 1, (n, rel, s.count(old))
            p.write_text(s.replace(old, new))


if __name__ == "__main__":
    src, dst, *names = sys.argv[1:]
    if Path(dst).exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    if names == ["--start"]:
        apply(dst, list(BUGS))
        strip_stage2(dst)
    else:
        apply(dst, names or list(BUGS))
