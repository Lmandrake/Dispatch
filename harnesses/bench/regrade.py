#!/usr/bin/env python3
"""Re-grade every run in runs.jsonl against the current hidden tests (workdirs are kept), writing
runs.regraded.jsonl beside it. Use after a hidden test is corrected, so all arms share one grader.

    python3 bench/regrade.py RUN_DIR [RUN_DIR ...]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capability_bench as capb  # noqa: E402

for run in sys.argv[1:]:
    out = []
    for line in open(os.path.join(run, "runs.jsonl")):
        r = json.loads(line)
        if r.get("workdir") and os.path.isdir(r["workdir"]):
            r["passed_original"] = r["passed"]
            r["passed"], r["pytest"] = capb.grade(r["task"], r["workdir"])
        out.append(r)
    with open(os.path.join(run, "runs.regraded.jsonl"), "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in out)
    print(run, sum(r["passed"] != r.get("passed_original", r["passed"]) for r in out), "changed")
