"""Command-line interface: ``python3 -m senslog <command> ...``.

Commands:
  info FILE                     header summary
  dump FILE [--sensor N]...     records as CSV on stdout
  import CSV OUT [--station S]  build a SLOG file from CSV
  stats FILE                    per-sensor statistics table
  verify FILE...                integrity check, one line per file
  filter IN OUT [criteria]      copy matching records to a new file
  merge OUT IN...               merge files in timestamp order

Exit status: 0 success, 1 verify found a corrupt file, 2 usage or data error.
"""
import argparse
import sys

from . import csvio, ops, stats
from .errors import SenslogError
from .reader import LogReader
from .timefmt import format_ts, parse_ts
from .verify import verify_file
from .writer import write_log


def _err(msg):
    print(f"senslog: {msg}", file=sys.stderr)


def cmd_info(args):
    rd = LogReader(args.file)
    print(f"file: {args.file}")
    print(f"version: {rd.version}")
    print(f"station: {rd.station}")
    print(f"created: {format_ts(rd.created)}")
    print(f"records: {len(rd)}")
    print(f"sensors: {' '.join(str(s) for s in rd.sensors()) or '-'}")
    if rd.records:
        first = min(r.timestamp for r in rd.records)
        last = max(r.timestamp for r in rd.records)
        print(f"range: {format_ts(first)} .. {format_ts(last)}")
    return 0


def cmd_dump(args):
    rd = LogReader(args.file)
    recs = rd.records
    if args.sensor:
        recs = list(ops.filter_records(recs, sensors=args.sensor))
    csvio.records_to_csv(recs, sys.stdout, header=not args.no_header)
    return 0


def cmd_import(args):
    with open(args.csv, newline="", encoding="utf-8") as fh:
        recs = csvio.records_from_csv(fh)
    created = parse_ts(args.created) if args.created else None
    n = write_log(args.out, recs, station=args.station, created=created)
    print(f"wrote {n} records to {args.out}")
    return 0


def cmd_stats(args):
    rd = LogReader(args.file)
    print(stats.format_table(stats.summarize(rd.records)))
    return 0


def cmd_verify(args):
    status = 0
    for path in args.files:
        rep = verify_file(path)
        print(rep.describe())
        if not rep.ok:
            status = 1
    return status


def cmd_filter(args):
    rd = LogReader(args.input)
    recs = ops.filter_records(
        rd.records,
        sensors=args.sensor or None,
        start=parse_ts(args.start) if args.start else None,
        end=parse_ts(args.end) if args.end else None,
        label_contains=args.label,
        calibrated=True if args.calibrated else (False if args.uncalibrated else None),
    )
    n = write_log(args.output, recs, station=rd.station, created=rd.created)
    print(f"wrote {n} records to {args.output}")
    return 0


def cmd_merge(args):
    readers = [LogReader(p) for p in args.inputs]
    recs = ops.merge(*(r.records for r in readers))
    if args.dedupe:
        recs = ops.dedupe(recs)
    station = args.station if args.station is not None else readers[0].station
    created = min(r.created for r in readers)
    n = write_log(args.output, recs, station=station, created=created)
    print(f"wrote {n} records to {args.output}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="senslog", description="SLOG sensor-log tool")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="header summary")
    s.add_argument("file")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("dump", help="records as CSV")
    s.add_argument("file")
    s.add_argument("--sensor", type=int, action="append")
    s.add_argument("--no-header", action="store_true")
    s.set_defaults(func=cmd_dump)

    s = sub.add_parser("import", help="build a SLOG file from CSV")
    s.add_argument("csv")
    s.add_argument("out")
    s.add_argument("--station", default="")
    s.add_argument("--created", help="creation time (ISO or epoch); default now")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("stats", help="per-sensor statistics")
    s.add_argument("file")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("verify", help="integrity check")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("filter", help="copy matching records")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--sensor", type=int, action="append")
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--label")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--calibrated", action="store_true")
    g.add_argument("--uncalibrated", action="store_true")
    s.set_defaults(func=cmd_filter)

    s = sub.add_parser("merge", help="merge files in timestamp order")
    s.add_argument("output")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--dedupe", action="store_true")
    s.add_argument("--station")
    s.set_defaults(func=cmd_merge)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SenslogError, ValueError, OSError) as exc:
        _err(str(exc))
        return 2
