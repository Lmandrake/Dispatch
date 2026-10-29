"""Runs INSIDE a network-less Linux container. Never run on the host.

Reads /work/jobs/*.json (key, qid, code) and /work/tests/<qid>.json (public, private,
testtype, func_name), writes /work/out/<name>.json
with per-test-set verdicts. Stops a test set at its first failure. Generated code is
untrusted; isolation is the container's job, timeouts are this file's.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

PRELUDE = ("from typing import *\nfrom collections import *\nfrom itertools import *\n"
           "from functools import *\nfrom heapq import *\nfrom bisect import *\n"
           "import math, sys, re, string, random, collections, itertools, heapq, bisect\n"
           "sys.setrecursionlimit(1 << 20)\n")

FUNC_DRIVER = """
import json, sys
_args = [json.loads(l) for l in sys.stdin.read().split("\\n") if l.strip()]
_r = getattr(Solution(), {fn!r})(*_args)
print(json.dumps(_r))
"""


def norm_stdout(s):
    return [ln.split() for ln in s.strip().splitlines() if ln.strip()]


def same(got, want):
    a, b = norm_stdout(got), norm_stdout(want)
    if a == b:
        return True
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if len(x) != len(y):
            return False
        for u, v in zip(x, y):
            if u == v:
                continue
            try:
                if abs(float(u) - float(v)) > 1e-6 * max(1, abs(float(v))):
                    return False
            except ValueError:
                return False
    return True


def run_set(path, tests, testtype, fn, timeout):
    for i, t in enumerate(tests):
        try:
            p = subprocess.run([sys.executable, path], input=t["input"], text=True,
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"pass": False, "failed_at": i, "why": "timeout"}
        if p.returncode != 0:
            return {"pass": False, "failed_at": i, "why": "error",
                    "stderr": p.stderr[-300:]}
        if testtype == "functional":
            try:
                ok = json.loads(p.stdout.strip()) == json.loads(t["output"])
            except Exception:
                ok = same(p.stdout, t["output"])
        else:
            ok = same(p.stdout, t["output"])
        if not ok:
            return {"pass": False, "failed_at": i, "why": "wrong"}
    return {"pass": True, "n": len(tests)}


def judge(job_path):
    job = json.loads(pathlib.Path(job_path).read_text())
    job.update(json.loads((pathlib.Path("/work/tests") / f"{job['qid']}.json").read_text()))
    out = pathlib.Path("/work/out") / pathlib.Path(job_path).name
    if out.exists():
        return
    res = {"key": job["key"]}
    code = job["code"]
    if not code:
        res.update(public={"pass": False, "why": "no_code"},
                   private={"pass": False, "why": "no_code"})
    else:
        src = PRELUDE + code
        if job["testtype"] == "functional":
            src += FUNC_DRIVER.format(fn=job["func_name"])
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(src)
        for name in ("public", "private"):
            res[name] = run_set(f.name, job[name], job["testtype"], job["func_name"],
                                job.get("timeout", 6))
        os.unlink(f.name)
    out.write_text(json.dumps(res))


if __name__ == "__main__":
    jobs = sorted(str(p) for p in pathlib.Path("/work/jobs").glob("*.json"))
    with ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 2) as ex:
        list(ex.map(judge, jobs))
    print("judged", len(jobs))
