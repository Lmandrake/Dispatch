#!/usr/bin/env python3
"""Median [min-max] per cell for one or more `cells`-plan runs, side by side.

    python3 bench/cells_table.py LABEL=DIR [LABEL=DIR ...]
"""
import json
import statistics as st
import sys


def cell(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    return "%.2f [%.2f-%.2f] n=%d" % (st.median(xs), min(xs), max(xs), len(xs))


def rows(d):
    rs = [json.loads(l) for l in open(d + "/runs.jsonl")]
    h = lambda t: [r for r in rs if r["kind"] == "headless" and r["task"] == t]
    i = [r for r in rs if r["kind"] == "idle"]
    c = [r for r in rs if r["kind"] == "concurrent"]
    pas = lambda xs, k="ok": "%d/%d" % (sum(bool(x.get(k)) for x in xs), len(xs))
    return [
        ("one-line reply, CPU-s (headless)", cell([r["rusage_cpu_s"] for r in h("pong")]) + " pass " + pas(h("pong"))),
        ("small tool task, CPU-s (headless)", cell([r["rusage_cpu_s"] for r in h("tools")]) + " pass " + pas(h("tools"))),
        ("interactive idle, %CPU (45 s)", cell([r["idle_cpu_pct"] for r in i])),
        ("interactive ~400-line output, CPU-s (40 s)", cell([r["prompt_cpu_s"] for r in i]) + " pass " + pas(i, "prompt_ok")),
        ("interactive startup, CPU-s", cell([r["startup_cpu_s"] for r in i])),
        ("8 at once, total CPU-s", cell([r["sum_rusage_cpu_s"] for r in c]) + " pass " + pas(c, "all_ok")),
        ("8 at once, batch wall s", cell([r["batch_wall_s"] for r in c])),
        ("peak memory headless, MB (tree)", cell([r["peak_tree_rss_mb"] for r in h("pong") + h("tools")])),
        ("peak memory interactive, MB (tree)", cell([r["peak_tree_rss_mb"] for r in i])),
        ("peak memory 8 at once, MB (sum)", cell([r["sum_peak_rss_mb"] for r in c])),
    ]


def main(args):
    labs = [a.split("=", 1) for a in args]
    tabs = [rows(d) for _, d in labs]
    out = ["| measure | " + " | ".join(l for l, _ in labs) + " |", "|---" * (len(labs) + 1) + "|"]
    for k in range(len(tabs[0])):
        out.append("| %s | %s |" % (tabs[0][k][0], " | ".join(t[k][1] for t in tabs)))
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
