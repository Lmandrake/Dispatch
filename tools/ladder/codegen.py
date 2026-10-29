"""Experiment B: a CHECKABLE task -- competitive programming (LiveCodeBench release v6).

The caller holds a cheap check (the problem's public example tests) and the truth is
the hidden private tests. That split is what lets this experiment ask the question the
SimpleQA run cannot: when a cheap check exists, does sampling the small model and
accepting only what passes the check recover the big model's accuracy, at what cost,
and how often does the cheap check pass a wrong answer?

Generated code runs ONLY inside a network-less Docker container (`judge_in_box.py`),
never on the host.

    python3 tools/ladder/codegen.py --prep --run --judge --report
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import pickle
import re
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor

import gw

SRC = ("https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/main/"
       "test6.jsonl")
DATA = gw.STORE.parent.parent / "scratch" / "ladder" / "lcb6.jsonl"
WORK = gw.STORE / "codegen-box"
SAMPLES = {"haiku": 5, "sonnet": 2, "opus": 1}

PROMPT_STDIN = """You will be given a competitive programming problem. Write a correct, efficient Python 3 program that reads from standard input and writes to standard output.

### Problem
{q}

Return the complete program in a single ```python code block."""

PROMPT_FUNC = """You will be given a programming problem. Complete the starter code with a correct, efficient Python 3 solution.

### Problem
{q}

### Starter code
```python
{starter}
```

Return the complete class in a single ```python code block."""


def problems():
    out = []
    for line in DATA.open():
        r = json.loads(line)
        pub = json.loads(r["public_test_cases"])
        try:
            priv = json.loads(r["private_test_cases"])
        except json.JSONDecodeError:
            priv = json.loads(pickle.loads(zlib.decompress(
                base64.b64decode(r["private_test_cases"].encode()))))
        md = json.loads(r["metadata"] or "{}")
        out.append({"qid": r["question_id"], "difficulty": r["difficulty"],
                    "platform": r["platform"], "q": r["question_content"],
                    "starter": r["starter_code"], "testtype": pub[0]["testtype"],
                    "func_name": md.get("func_name"), "public": pub, "private": priv})
    return out


def prep(ps):
    (WORK / "tests").mkdir(parents=True, exist_ok=True)
    (WORK / "jobs").mkdir(exist_ok=True)
    (WORK / "out").mkdir(exist_ok=True)
    for p in ps:
        f = WORK / "tests" / f"{p['qid']}.json"
        if not f.exists():
            f.write_text(json.dumps({k: p[k] for k in
                                     ("public", "private", "testtype", "func_name")}))
    (WORK / "judge_in_box.py").write_text(
        (pathlib.Path(__file__).parent / "judge_in_box.py").read_text())
    print("prepped", len(ps))


def extract(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return blocks[-1] if blocks else ""


def run(ps, workers=16):
    cache = gw.Cache("codegen-answers")
    jobs = [(p, role, s) for p in ps for role, k in SAMPLES.items() for s in range(k)
            if not cache.get(f"{p['qid']}|{role}|{s}")]
    print(f"{len(jobs)} generation calls to make")

    def do(j):
        p, role, s = j
        prompt = (PROMPT_FUNC.format(q=p["q"], starter=p["starter"])
                  if p["testtype"] == "functional" else PROMPT_STDIN.format(q=p["q"]))
        r = gw.call(role, prompt, max_tokens=64000)
        if "error" not in r:
            r["code"] = extract(r["text"])
            r.pop("text")
        r.update(qid=p["qid"], difficulty=p["difficulty"], sample=s)
        return cache.put(f"{p['qid']}|{role}|{s}", r)

    with ThreadPoolExecutor(workers) as ex:
        for k, _ in enumerate(ex.map(do, jobs)):
            if k % 50 == 0:
                print(f"  {k}/{len(jobs)} spend ${cache.spend():.2f}", flush=True)
    print(f"generation spend ${cache.spend():.2f}")


def judge():
    cache = gw.Cache("codegen-answers")
    n = 0
    for key, r in cache.rows.items():
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json"
        f = WORK / "jobs" / name
        if not f.exists():
            f.write_text(json.dumps({"key": key, "qid": r["qid"], "code": r["code"]}))
            n += 1
    print("new judge jobs", n)
    subprocess.run(["docker", "run", "--rm", "--network", "none", "--memory", "3g",
                    "--cpus", "2", "-v", f"{WORK}:/work", "python:3.12-slim",
                    "python", "/work/judge_in_box.py", "2"], check=True)


def verdicts():
    out = {}
    for f in (WORK / "out").glob("*.json"):
        r = json.loads(f.read_text())
        out[r["key"]] = r
    return out


def report(ps):
    cache = gw.Cache("codegen-answers")
    v = verdicts()
    diff = {p["qid"]: p["difficulty"] for p in ps}
    rows = []
    for key, r in cache.rows.items():
        if key in v:
            rows.append(dict(r, pub=v[key]["public"]["pass"], priv=v[key]["private"]["pass"]))
    by = {}
    for r in rows:
        by.setdefault(r["role"], {}).setdefault(r["qid"], []).append(r)
    rep = {"source": SRC, "n_problems": len(ps), "per_model": {}, "strategies": {}}

    for role, qs in by.items():
        flat = [r for rs in qs.values() for r in rs]
        pub_pass = [r for r in flat if r["pub"]]
        rep["per_model"][role] = {
            "samples": len(flat),
            "pass_at_1_private": sum(r["priv"] for r in flat) / len(flat),
            "public_pass_rate": len(pub_pass) / len(flat),
            # the cheap check's false-accept: passes the examples, fails the hidden tests
            "false_accept_given_public_pass":
                sum(not r["priv"] for r in pub_pass) / len(pub_pass) if pub_pass else None,
            "cost_per_sample": sum(r["cost"] for r in flat) / len(flat),
            "median_latency_s": sorted(r["latency"] for r in flat)[len(flat) // 2],
            "by_difficulty": {d: _rate([r for r in flat if diff[r["qid"]] == d])
                              for d in ("easy", "medium", "hard")},
        }

    qids = [p["qid"] for p in ps if all(p["qid"] in by.get(m, {}) for m in SAMPLES)]

    def strat(name, fn):
        res = [fn(q) for q in qids]
        rep["strategies"][name] = {
            "n": len(res), "correct": sum(x[0] for x in res) / len(res),
            "cost_per_problem": sum(x[1] for x in res) / len(res),
            "latency_per_problem_s": sum(x[2] for x in res) / len(res),
            "accepted_wrong": sum(x[3] for x in res) / len(res),
            "by_difficulty": {d: sum(x[0] for q, x in zip(qids, res) if diff[q] == d)
                              / max(1, sum(diff[q] == d for q in qids))
                              for d in ("easy", "medium", "hard")}}

    def single(role):
        def f(q):
            r = by[role][q][0]
            return r["priv"], r["cost"], r["latency"], (not r["priv"])
        return f

    def checked(small, k, big):
        """Draw up to k samples of `small`; take the first that passes the public tests;
        if none does, pay `big` once and take its answer unchecked."""
        def f(q):
            cost = lat = 0.0
            for r in by[small][q][:k]:
                cost += r["cost"]
                lat += r["latency"]
                if r["pub"]:
                    return r["priv"], cost, lat, (not r["priv"])
            b = by[big][q][0]
            return b["priv"], cost + b["cost"], lat + b["latency"], (not b["priv"])
        return f

    for role in SAMPLES:
        strat(f"{role} x1 unchecked", single(role))
    for k in (1, 3, 5):
        strat(f"haiku up to {k}, check=public tests, else opus", checked("haiku", k, "opus"))
    strat("sonnet up to 2, check=public tests, else opus", checked("sonnet", 2, "opus"))
    strat("haiku up to 5, check=public tests, else sonnet", checked("haiku", 5, "sonnet"))

    p = gw.STORE / "codegen-report.json"
    p.write_text(json.dumps(rep, indent=1))
    for m, a in rep["per_model"].items():
        print(f"{m:7s} pass@1={a['pass_at_1_private']:.3f} public={a['public_pass_rate']:.3f} "
              f"false_accept={a['false_accept_given_public_pass']:.3f} "
              f"$/sample={a['cost_per_sample']:.4f} med={a['median_latency_s']:.0f}s "
              f"{a['by_difficulty']}")
    for s, a in rep["strategies"].items():
        print(f"{s:48s} correct={a['correct']:.3f} $={a['cost_per_problem']:.4f} "
              f"t={a['latency_per_problem_s']:.0f}s wrong_accepted={a['accepted_wrong']:.3f} "
              f"{a['by_difficulty']}")
    print(p)


def _rate(rs):
    return round(sum(r["priv"] for r in rs) / len(rs), 3) if rs else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for f in ("prep", "run", "judge", "report"):
        ap.add_argument(f"--{f}", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    ps = problems()[: a.limit] if a.limit else problems()
    if a.prep:
        prep(ps)
    if a.run:
        run(ps)
    if a.judge:
        judge()
    if a.report:
        report(ps)
