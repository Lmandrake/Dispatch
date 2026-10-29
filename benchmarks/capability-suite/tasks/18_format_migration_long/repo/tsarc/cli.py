"""Command-line interface: ``python3 -m tsarc <command> ...``.

Commands:
  info FILE                          structure, schema, range and metadata
  schema FILE                        the schema text
  head FILE [-n N]                   first rows as CSV
  tail FILE [-n N]                   last rows as CSV
  export FILE [--format csv|jsonl] [-o OUT] [--columns C,...]
  import CSV OUT [--schema S] [--meta k=v]... [--format-version V]
  query FILE [--start T] [--end T] [--where EXPR] [--columns C,...] [--format csv|jsonl|count]
  stats FILE [--start T] [--end T]   per-column statistics table
  verify FILE...                     integrity check, one line per file
  convert SRC DST --format-version V rewrite in another format version
  merge OUT IN... [--format-version V]
  append FILE CSV                    append CSV rows to an archive
  resample FILE OUT --every DUR [--agg NAME | --agg col=name,...]
  dedupe FILE OUT [--columns C,...] [--keep first|last]
  fill FILE OUT --method M [--value X] [--columns C,...]
  gaps FILE --threshold DUR
  hist FILE COLUMN [--bins N]
  sample FILE OUT (--every-nth N | --reservoir K [--seed S])
  partition FILE DIR --by hour|day|month|year [--prefix P]
  meta FILE [--set k=v]... [--unset k]...
  diff A B                           compare two archives row by row
  ls DIR [--start T] [--end T]       catalog of the archives in a directory
  derive FILE OUT name=EXPR...       add computed columns
  check FILE [--rules F] [--gap DUR] data-quality findings (exit 1 if any)
  downsample FILE OUT COLUMN -n N    LTTB down-sampling for plotting
  report FILE [--title T]            Markdown summary
  groupby FILE KEY[,KEY] --agg col=name,...   grouped aggregates table
  outliers FILE COLUMN [--method zscore|mad] [-k K] [--drop OUT]
  spark FILE COLUMN [--width N]      one-line sparkline
  plot FILE COLUMN [--width N] [--height N]
  units FILE OUT COLUMN TO [--from U]
  manifest DIR [--check]             write or check MANIFEST.json
  lp-export FILE OUT --measurement M line protocol export
  lp-import LP OUT [--measurement M] line protocol import
  rollup FILE OUT --by day|week|month|year --agg col=name,... [--tz +HH:MM]
  compare A B                        column distribution comparison
  ewma FILE OUT COLUMN --halflife DUR

Times on the command line are ISO-8601 (``2026-03-01T12:00:00Z``), ``@<microseconds>``,
or a bare integer meaning epoch seconds.  Durations look like ``90s``, ``5m``, ``1h30m``.

Exit status: 0 success, 1 ``verify`` found a bad file or ``diff`` found a difference,
2 usage or data error.
"""
import argparse
import sys

from . import catalog, csvio, jsonio
from . import metadata as md
from .archive import (ArchiveReader, append_rows, convert, set_metadata, write_archive)
from .codec import known_versions
from .diff import diff_tables
from .errors import TsarcError
from .fill import fill_table
from .hist import render_histogram
from .info import info_lines
from .ops.derive import derive_many
from .ops.lttb import lttb
from .quality import parse_rules, run_checks
from .report import markdown_report
from . import manifest as mf
from .chart import line_chart
from .ops.groupby import format_rows, groupby
from .ops.outliers import drop_outliers, find_outliers
from .render import render_table
from .spark import column_sparkline
from .units import convert_column
from . import compare as cmp
from . import lineproto, rollup as ru
from .ops.window import ewma
from .tz import parse_offset
from .ops import dedupe, find_gaps, merge_tables, resample
from .ops.partition import PERIODS, write_partitions
from .ops.sample import every_nth, reservoir
from .stats import render_stats, time_stats
from .timeutil import format_duration, format_ts, parse_duration, parse_ts
from .verify import verify_paths


def _err(msg):
    print(f"tsarc: {msg}", file=sys.stderr)


def _columns_arg(text):
    if text is None:
        return None
    return [c.strip() for c in text.split(",") if c.strip()]


def _version_arg(text):
    try:
        v = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a version number: {text!r}") from None
    return v


def _write_output(table, fmt, out_path):
    if out_path:
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            return _emit(table, fmt, fh)
    return _emit(table, fmt, sys.stdout)


def _emit(table, fmt, fh):
    if fmt == "jsonl":
        return jsonio.table_to_jsonl(table, fh)
    return csvio.table_to_csv(table, fh)


# -- commands ---------------------------------------------------------------------------------

def cmd_info(args):
    rd = ArchiveReader(args.file)
    for line in info_lines(rd, args.file):
        print(line)
    return 0


def cmd_schema(args):
    print(ArchiveReader(args.file).schema.to_text())
    return 0


def cmd_head(args):
    csvio.table_to_csv(ArchiveReader(args.file).table.head(args.n), sys.stdout)
    return 0


def cmd_tail(args):
    csvio.table_to_csv(ArchiveReader(args.file).table.tail(args.n), sys.stdout)
    return 0


def cmd_export(args):
    table = ArchiveReader(args.file).table
    cols = _columns_arg(args.columns)
    if cols:
        table = table.select(cols)
    _write_output(table, args.format, args.output)
    return 0


def cmd_import(args):
    table = csvio.read_csv_file(args.csv, args.schema)
    meta = dict(md.parse_assignment(m) for m in args.meta)
    n = write_archive(args.out, table, meta, args.format_version)
    print(f"imported {n} rows into {args.out}")
    return 0


def _range_args(args):
    start = parse_ts(args.start) if args.start else None
    end = parse_ts(args.end) if args.end else None
    return start, end


def cmd_query(args):
    rd = ArchiveReader(args.file)
    start, end = _range_args(args)
    table = rd.query(start, end, columns=_columns_arg(args.columns), where=args.where)
    if args.format == "count":
        print(table.num_rows)
        return 0
    _emit(table, args.format, sys.stdout)
    return 0


def cmd_stats(args):
    rd = ArchiveReader(args.file)
    start, end = _range_args(args)
    table = rd.query(start, end) if (start is not None or end is not None) else rd.table
    print(render_stats(table))
    ts = time_stats(table)
    if ts is None:
        print("time: no rows")
    else:
        first, last, span, rate = ts
        rate_text = "-" if rate is None else f"{rate:.6g}/s"
        print(f"time: {format_ts(first)} .. {format_ts(last)} (span {span:g}s, rate {rate_text})")
    return 0


def cmd_verify(args):
    bad = 0
    for res in verify_paths(args.files):
        print(res.line())
        if not res.ok:
            bad += 1
    return 1 if bad else 0


def cmd_convert(args):
    n = convert(args.src, args.dst, args.format_version)
    print(f"converted {n} rows to version {args.format_version}: {args.dst}")
    return 0


def cmd_merge(args):
    readers = [ArchiveReader(p) for p in args.inputs]
    merged = merge_tables([r.table for r in readers])
    n = write_archive(args.out, merged, readers[0].metadata, args.format_version)
    print(f"merged {len(readers)} files, {n} rows into {args.out}")
    return 0


def cmd_append(args):
    rd = ArchiveReader(args.file)
    table = csvio.read_csv_file(args.csv, rd.schema)
    total = append_rows(args.file, table)
    print(f"appended {table.num_rows} rows, {total} rows total")
    return 0


def _agg_arg(text):
    if "=" not in text:
        return text
    out = {}
    for part in text.split(","):
        col, _, name = part.partition("=")
        out.setdefault(col.strip(), []).append(name.strip())
    return out


def cmd_resample(args):
    rd = ArchiveReader(args.file)
    every = parse_duration(args.every)
    out = resample(rd.table, every, _agg_arg(args.agg))
    n = write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"resampled {rd.num_rows} rows into {n} buckets of {format_duration(every)}")
    return 0


def cmd_dedupe(args):
    rd = ArchiveReader(args.file)
    out = dedupe(rd.table, _columns_arg(args.columns), args.keep)
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"kept {out.num_rows} of {rd.num_rows} rows")
    return 0


def cmd_fill(args):
    rd = ArchiveReader(args.file)
    out = fill_table(rd.table, _columns_arg(args.columns), args.method, args.value)
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"filled {args.out}")
    return 0


def cmd_gaps(args):
    rd = ArchiveReader(args.file)
    gaps = find_gaps(rd.table, parse_duration(args.threshold))
    for g in gaps:
        print(f"{format_ts(g.start)} .. {format_ts(g.end)}  ({format_duration(g.length)})")
    print(f"{len(gaps)} gaps")
    return 0


def cmd_hist(args):
    print(render_histogram(ArchiveReader(args.file).table, args.column, args.bins))
    return 0


def cmd_sample(args):
    rd = ArchiveReader(args.file)
    if args.every_nth is not None:
        out = every_nth(rd.table, args.every_nth)
    else:
        out = reservoir(rd.table, args.reservoir, args.seed)
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"sampled {out.num_rows} of {rd.num_rows} rows")
    return 0


def cmd_partition(args):
    rd = ArchiveReader(args.file)
    written = write_partitions(rd.table, args.dir, args.by, args.prefix, rd.metadata,
                               args.format_version)
    for path, rows in written:
        print(f"{path}: {rows} rows")
    return 0


def cmd_meta(args):
    if not args.set and not args.unset:
        for line in md.format_lines(ArchiveReader(args.file).metadata):
            print(line)
        return 0
    pairs = [md.parse_assignment(s) for s in args.set]
    new = set_metadata(args.file, pairs, args.unset)
    for line in md.format_lines(new):
        print(line)
    return 0


def cmd_diff(args):
    a = ArchiveReader(args.a).table
    b = ArchiveReader(args.b).table
    d = diff_tables(a, b)
    for line in d.lines():
        print(line)
    return 0 if d.equal else 1


def cmd_ls(args):
    entries = catalog.scan(args.dir)
    start, end = _range_args(args)
    if start is not None or end is not None:
        entries = catalog.find(entries, start, end)
    print(catalog.render(entries, base=args.dir))
    return 0


def cmd_derive(args):
    rd = ArchiveReader(args.file)
    out = derive_many(rd.table, args.assignments, replace=args.replace)
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"wrote {out.num_rows} rows with columns {out.schema.to_text()}")
    return 0


def cmd_check(args):
    rd = ArchiveReader(args.file)
    rules = []
    if args.rules:
        with open(args.rules, encoding="utf-8") as fh:
            rules = parse_rules(fh.read())
    gap = parse_duration(args.gap) if args.gap else None
    findings = run_checks(rd.table, rules, gap)
    for f in findings[:args.limit]:
        print(f.line())
    if len(findings) > args.limit:
        print(f"... {len(findings) - args.limit} more")
    print(f"{len(findings)} findings")
    return 1 if findings else 0


def cmd_downsample(args):
    rd = ArchiveReader(args.file)
    out = lttb(rd.table, args.column, args.n)
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"kept {out.num_rows} of {rd.num_rows} rows")
    return 0


def cmd_report(args):
    print(markdown_report(ArchiveReader(args.file), args.title))
    return 0


def cmd_groupby(args):
    rd = ArchiveReader(args.file)
    keys = _columns_arg(args.keys)
    aggs = _agg_arg(args.agg)
    if isinstance(aggs, str):
        raise TsarcError("groupby needs --agg col=name[,col=name...]")
    names, rows = groupby(rd.table, keys, aggs)
    cells = format_rows(names, rows, rd.schema)
    align = "".join("l" if n in keys else "r" for n in names)
    print(render_table(names, cells, align=align))
    return 0


def cmd_outliers(args):
    rd = ArchiveReader(args.file)
    if args.drop:
        out = drop_outliers(rd.table, args.column, args.method, args.k)
        write_archive(args.drop, out, rd.metadata, args.format_version)
        print(f"kept {out.num_rows} of {rd.num_rows} rows")
        return 0
    idx = find_outliers(rd.table, args.column, args.method, args.k)
    ts = rd.table.time_values()
    vals = rd.table.column_view(args.column)
    for i in idx:
        print(f"row {i}  {format_ts(ts[i])}  {vals[i]!r}")
    print(f"{len(idx)} outliers")
    return 0


def cmd_spark(args):
    print(column_sparkline(ArchiveReader(args.file).table, args.column, args.width))
    return 0


def cmd_plot(args):
    print(line_chart(ArchiveReader(args.file).table, args.column, args.width, args.height))
    return 0


def cmd_units(args):
    rd = ArchiveReader(args.file)
    table, meta = convert_column(rd.table, rd.metadata, args.column, args.to, args.src)
    write_archive(args.out, table, meta, args.format_version)
    print(f"converted {args.column} to {args.to}")
    return 0


def cmd_manifest(args):
    if args.check:
        problems = mf.check_manifest(args.dir)
        for line in problems:
            print(line)
        print("manifest ok" if not problems else f"{len(problems)} problems")
        return 1 if problems else 0
    m = mf.write_manifest(args.dir)
    print(f"wrote {mf.NAME} with {len(m['files'])} files")
    return 0


def cmd_lp_export(args):
    n = lineproto.write_lines(args.out, ArchiveReader(args.file).table, args.measurement)
    print(f"wrote {n} lines to {args.out}")
    return 0


def cmd_lp_import(args):
    table = lineproto.read_lines(args.lp, args.measurement)
    n = write_archive(args.out, table, None, args.format_version)
    print(f"imported {n} rows into {args.out}")
    return 0


def cmd_rollup(args):
    rd = ArchiveReader(args.file)
    aggs = _agg_arg(args.agg)
    if isinstance(aggs, str):
        raise TsarcError("rollup needs --agg col=name[,col=name...]")
    out = ru.rollup(rd.table, args.by, aggs, parse_offset(args.tz))
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"rolled {rd.num_rows} rows into {out.num_rows} {args.by} buckets")
    return 0


def cmd_compare(args):
    print(cmp.render(cmp.compare_tables(ArchiveReader(args.a).table, ArchiveReader(args.b).table)))
    return 0


def cmd_ewma(args):
    rd = ArchiveReader(args.file)
    out = ewma(rd.table, args.column, parse_duration(args.halflife))
    write_archive(args.out, out, rd.metadata, args.format_version)
    print(f"wrote {args.out}")
    return 0


# -- parser -----------------------------------------------------------------------------------

def _add_version(p):
    p.add_argument("--format-version", type=_version_arg, default=None,
                   help=f"format version to write (known: {', '.join(map(str, known_versions()))}; "
                        f"default 2)")


def _add_range(p):
    p.add_argument("--start", help="first time to include")
    p.add_argument("--end", help="first time to exclude")


def build_parser():
    ap = argparse.ArgumentParser(prog="tsarc", description="columnar time-series archives")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info")
    p.add_argument("file")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("schema")
    p.add_argument("file")
    p.set_defaults(func=cmd_schema)

    for name, func in (("head", cmd_head), ("tail", cmd_tail)):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("-n", type=int, default=10)
        p.set_defaults(func=func)

    p = sub.add_parser("export")
    p.add_argument("file")
    p.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    p.add_argument("-o", "--output")
    p.add_argument("--columns")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import")
    p.add_argument("csv")
    p.add_argument("out")
    p.add_argument("--schema")
    p.add_argument("--meta", action="append", default=[])
    _add_version(p)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("query")
    p.add_argument("file")
    _add_range(p)
    p.add_argument("--where")
    p.add_argument("--columns")
    p.add_argument("--format", choices=["csv", "jsonl", "count"], default="csv")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("stats")
    p.add_argument("file")
    _add_range(p)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("verify")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("convert")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--format-version", type=_version_arg, required=True)
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("merge")
    p.add_argument("out")
    p.add_argument("inputs", nargs="+")
    _add_version(p)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("append")
    p.add_argument("file")
    p.add_argument("csv")
    p.set_defaults(func=cmd_append)

    p = sub.add_parser("resample")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("--every", required=True)
    p.add_argument("--agg", default="mean")
    _add_version(p)
    p.set_defaults(func=cmd_resample)

    p = sub.add_parser("dedupe")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("--columns")
    p.add_argument("--keep", choices=["first", "last"], default="first")
    _add_version(p)
    p.set_defaults(func=cmd_dedupe)

    p = sub.add_parser("fill")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("--method", choices=["forward", "backward", "linear", "value"], required=True)
    p.add_argument("--value", type=float)
    p.add_argument("--columns")
    _add_version(p)
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("gaps")
    p.add_argument("file")
    p.add_argument("--threshold", required=True)
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("hist")
    p.add_argument("file")
    p.add_argument("column")
    p.add_argument("--bins", type=int, default=10)
    p.set_defaults(func=cmd_hist)

    p = sub.add_parser("sample")
    p.add_argument("file")
    p.add_argument("out")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--every-nth", type=int)
    g.add_argument("--reservoir", type=int)
    p.add_argument("--seed", type=int, default=0)
    _add_version(p)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("partition")
    p.add_argument("file")
    p.add_argument("dir")
    p.add_argument("--by", choices=PERIODS, required=True)
    p.add_argument("--prefix", default="part")
    _add_version(p)
    p.set_defaults(func=cmd_partition)

    p = sub.add_parser("meta")
    p.add_argument("file")
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--unset", action="append", default=[])
    p.set_defaults(func=cmd_meta)

    p = sub.add_parser("diff")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("ls")
    p.add_argument("dir")
    _add_range(p)
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("derive")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("assignments", nargs="+")
    p.add_argument("--replace", action="store_true")
    _add_version(p)
    p.set_defaults(func=cmd_derive)

    p = sub.add_parser("check")
    p.add_argument("file")
    p.add_argument("--rules")
    p.add_argument("--gap")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("downsample")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("column")
    p.add_argument("-n", type=int, required=True)
    _add_version(p)
    p.set_defaults(func=cmd_downsample)

    p = sub.add_parser("report")
    p.add_argument("file")
    p.add_argument("--title")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("groupby")
    p.add_argument("file")
    p.add_argument("keys")
    p.add_argument("--agg", required=True)
    p.set_defaults(func=cmd_groupby)

    p = sub.add_parser("outliers")
    p.add_argument("file")
    p.add_argument("column")
    p.add_argument("--method", choices=["zscore", "mad"], default="mad")
    p.add_argument("-k", type=float, default=3.5)
    p.add_argument("--drop")
    _add_version(p)
    p.set_defaults(func=cmd_outliers)

    p = sub.add_parser("spark")
    p.add_argument("file")
    p.add_argument("column")
    p.add_argument("--width", type=int, default=60)
    p.set_defaults(func=cmd_spark)

    p = sub.add_parser("plot")
    p.add_argument("file")
    p.add_argument("column")
    p.add_argument("--width", type=int, default=60)
    p.add_argument("--height", type=int, default=12)
    p.set_defaults(func=cmd_plot)

    p = sub.add_parser("units")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("column")
    p.add_argument("to")
    p.add_argument("--from", dest="src")
    _add_version(p)
    p.set_defaults(func=cmd_units)

    p = sub.add_parser("manifest")
    p.add_argument("dir")
    p.add_argument("--check", action="store_true")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("lp-export")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("--measurement", required=True)
    p.set_defaults(func=cmd_lp_export)

    p = sub.add_parser("lp-import")
    p.add_argument("lp")
    p.add_argument("out")
    p.add_argument("--measurement")
    _add_version(p)
    p.set_defaults(func=cmd_lp_import)

    p = sub.add_parser("rollup")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("--by", choices=ru.PERIODS, required=True)
    p.add_argument("--agg", required=True)
    p.add_argument("--tz", default="Z")
    _add_version(p)
    p.set_defaults(func=cmd_rollup)

    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("ewma")
    p.add_argument("file")
    p.add_argument("out")
    p.add_argument("column")
    p.add_argument("--halflife", required=True)
    _add_version(p)
    p.set_defaults(func=cmd_ewma)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except TsarcError as exc:
        _err(str(exc))
        return 2
    except OSError as exc:
        _err(str(exc))
        return 2
