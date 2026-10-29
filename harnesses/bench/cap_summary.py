#!/usr/bin/env python3
"""Tables for a capability run: pass counts per task and arm, medians of cost and effort.

    python3 bench/cap_summary.py RUN_DIR [> SUMMARY.md]
Reads runs.regraded.jsonl if present, else runs.jsonl.
"""
import json
import os
import statistics as st
import sys
from collections import defaultdict

run = sys.argv[1]
f = os.path.join(run, "runs.regraded.jsonl")
R = [json.loads(l) for l in open(f if os.path.exists(f) else os.path.join(run, "runs.jsonl"))]
meta = json.load(open(os.path.join(run, "meta.json")))
arms = meta["arms"]
tasks = sorted({r["task"] for r in R})
print("# %s\n\nmodel %s, thinking %s, %d runs, jobs %s, %s to %s. Graded from %s.\n" % (
    os.path.basename(run), meta["model"], meta["thinking"], len(R), meta["jobs"], meta["started"],
    meta.get("finished"), os.path.basename(f) if os.path.exists(f) else "runs.jsonl"))
print("| task | " + " | ".join(arms) + " |\n|---|" + "---|" * len(arms))
for t in tasks:
    print("| %s | " % t + " | ".join("%d/%d" % (sum(r["passed"] for r in R if r["task"] == t and r["arm"] == a),
          sum(1 for r in R if r["task"] == t and r["arm"] == a)) for a in arms) + " |")
print("| **total** | " + " | ".join("**%d/%d**" % (sum(r["passed"] for r in R if r["arm"] == a),
      sum(1 for r in R if r["arm"] == a)) for a in arms) + " |")
print("\nMedians per run (all tasks):\n\n| measure | " + " | ".join(arms) + " |\n|---|" + "---|" * len(arms))
for k in ["wall_s", "cpu_s", "peak_rss_mb", "turns", "tool_calls", "out", "cache_read", "cache_write"]:
    print("| %s | " % k + " | ".join(str(round(st.median([r.get(k) or 0 for r in R if r["arm"] == a]), 1))
                                       for a in arms) + " |")
print("\nSum of wall_s per arm: " + ", ".join("%s %.0f" % (a, sum(r.get("wall_s") or 0 for r in R if r["arm"] == a)) for a in arms))
print("\nMedian wall_s per task:\n\n| task | " + " | ".join(arms) + " |\n|---|" + "---|" * len(arms))
for t in tasks:
    print("| %s | " % t + " | ".join(str(round(st.median([r.get("wall_s") or 0 for r in R if r["task"] == t and r["arm"] == a]), 1)) for a in arms) + " |")
print("\nTool calls, summed:\n")
for a in arms:
    tot = defaultdict(int)
    for r in R:
        if r["arm"] == a:
            for n, c in (r.get("tools") or {}).items():
                tot[n] += c
    print("- %s: %s" % (a, ", ".join("%s %d" % kv for kv in sorted(tot.items(), key=lambda x: -x[1]))))
fails = [r for r in R if not r["passed"]]
if fails:
    print("\nFailures:\n")
    for r in fails:
        print("- %s %s r%s: rc=%s timed_out=%s pytest `%s` %s" % (r["task"], r["arm"], r["rep"], r.get("rc"),
              r.get("timed_out"), r.get("pytest"), (r.get("stderr_tail") or "").strip().splitlines()[-1:] or ""))
