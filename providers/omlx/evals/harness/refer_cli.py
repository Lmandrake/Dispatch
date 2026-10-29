"""`bin/refer` -- read-only CLI over the referred classifier.

Separate from `refer.py` so the library stays importable with no argparse/stdout
concerns, matching how `router.py` and `bin/route` are split.
"""

from __future__ import annotations

import argparse
import sys

from evals.harness.refer import (ALIASES, JOBS, METRICS, Corpus, assess,
                                 known_models)
from evals.harness.router import DELEGATE, DO_NOT, UNKNOWN, VERIFY

_MARK = {DELEGATE: "OK  ", VERIFY: "CHECK", DO_NOT: "NO  ", UNKNOWN: "?   "}


def _fmt_pct(p) -> str:
    return "  --" if p is None else f"{p:5.0%}"


def cmd_jobs(_args) -> int:
    print("job kinds, and the skills a model must have to be handed one\n")
    for jid, j in JOBS.items():
        print(f"  {jid:6s} {j['label']}")
        print(f"         needs: {', '.join(j['skills'])}")
    print("\nA job's score is the MINIMUM over its skills, not the average: a model "
          "that\nfollows instructions well and fabricates is not partly good at "
          "attribution.")
    return 0


def cmd_models(_args) -> int:
    print("model id -> published name (precision, correspondence)\n")
    for mid in known_models():
        pub, prec, basis = ALIASES[mid]
        print(f"  {mid:38s} -> {pub:34s} {prec:5s} {basis}")
    print("\nNOT resolvable, deliberately: remote-118b-128k (remote enterprise service). It has no "
          "published\nleaderboard entry under that name. A guess would be worse than UNKNOWN.")
    return 0


def cmd_sources(_args) -> int:
    c = Corpus()
    print(f"reference corpus: {c.root}\n")
    for name, present in c.available().items():
        print(f"  {'present' if present else 'MISSING'}  {name}")
    print("\nmetric distributions (n = models carrying the metric)\n")
    for mid, m in METRICS.items():
        dist = c.distribution(mid)
        rng = (f"{min(dist):.3g} .. {max(dist):.3g}" if dist else "--")
        arrow = "higher better" if m["higher_is_better"] else "LOWER better"
        print(f"  {mid:22s} n={len(dist):4d}  {rng:20s} {arrow}")
        print(f"     {m['note']}")
    return 0


def _print_one(r: dict, verbose: bool) -> None:
    print(f"{_MARK[r['tier']]} {r['tier']:9s} {r['model']}  ->  {r['job']} "
          f"{r['job_label']}")
    print(f"      published as {r['published_as']!r}"
          f"{' at ' + r['precision'] if r['precision'] else ''}"
          f"  (correspondence: {r['alias_basis']})")
    print(f"      score {_fmt_pct(r['score'])}  = weakest skill")
    for s in r["skills"]:
        line = f"      {s['skill']:22s} {_fmt_pct(s['pctile'])}"
        if s["pctile"] is None:
            print(f"{line}   {s['why']}")
            continue
        ch = s["chosen"]
        line += (f"   from {ch['metric']} raw={ch['raw']:.3g} "
                 f"(pctile of n={ch['n']})")
        print(line)
        if s.get("haircut"):
            print(f"        haircut {s['haircut']:.0%}: {s['haircut_cite']}")
        if verbose:
            for c in s["sources"]:
                print(f"        source {c['metric']:20s} raw={c['raw']:.3g} "
                      f"pctile={c['pctile']:.0%} n={c['n']}")
                print(f"          {c['note']}")
    if r["tier"] == UNKNOWN:
        print("      UNKNOWN means no published metric covers a required skill. "
              "That is a\n      refusal to guess, not a low score.")
    if verbose:
        print("\n      limits:")
        for lim in r["limits"]:
            print(f"        - {lim}")


def cmd_show(args) -> int:
    r = assess(args.model, args.job)
    _print_one(r, args.verbose)
    return 0


def cmd_table(args) -> int:
    rows = [assess(m, args.job) for m in known_models()]
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))
    j = JOBS[args.job]
    print(f"{args.job}  {j['label']}")
    print(f"needs: {', '.join(j['skills'])}\n")
    print(f"  {'tier':10s} {'score':>6s}  {'model':38s} basis")
    for r in rows:
        print(f"  {r['tier']:10s} {_fmt_pct(r['score']):>6s}  "
              f"{r['model']:38s} {r['alias_basis']}"
              f"{'  haircut' if any(s.get('haircut') for s in r['skills']) else ''}")
    print("\nDELEGATE requires a MEASURED correspondence and no quantisation "
          "haircut.\nAn estimated or proxy match caps at VERIFY however high it "
          "scores.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bin/refer",
        description="Delegation tiers from published benchmarks. Calls no model.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("jobs").set_defaults(fn=cmd_jobs)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    sub.add_parser("sources").set_defaults(fn=cmd_sources)
    s = sub.add_parser("show")
    s.add_argument("model")
    s.add_argument("job")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_show)
    t = sub.add_parser("table")
    t.add_argument("job")
    t.set_defaults(fn=cmd_table)
    args = ap.parse_args(argv)
    if getattr(args, "job", None) is not None and args.job not in JOBS:
        ap.error(f"unknown job {args.job!r}; known: {', '.join(JOBS)}")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
