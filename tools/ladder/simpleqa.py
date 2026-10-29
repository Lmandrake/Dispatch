"""Experiment A: an UNCHECKABLE task -- short factual recall (OpenAI SimpleQA).

Every question is short and simple to state; the answer cannot be checked by the
caller without looking it up. Measures, per model x effort: correct / incorrect /
not-attempted, cost, latency, and whether the model's own stated confidence is a
usable escalation signal (the only cheap check available for this kind of task).

Grading uses OpenAI's published SimpleQA grader template verbatim, on Sonnet 5.5 at
low effort, and the grader is calibrated on known-correct / known-wrong / empty cases
before any model is scored (`--calibrate`).

    python3 tools/ladder/simpleqa.py --n 400 --calibrate --run --grade --report
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import gw

DATA = gw.STORE.parent.parent / "scratch" / "ladder" / "simpleqa.csv"
SRC = "https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv"
ARMS = [("haiku", None), ("sonnet", None), ("opus", None), ("opus", "low"), ("haiku", "high")]

PROMPT = ("{q}\n\nAnswer concisely. Then, on the last line, write exactly "
          "\"Confidence: N%\" where N is your probability (0-100) that your answer is "
          "correct. If you do not know, say so.")

# OpenAI simple-evals simpleqa_eval.py GRADER_TEMPLATE, fetched 2026-10-20 from
# https://raw.githubusercontent.com/openai/simple-evals/main/simpleqa_eval.py
GRADER_SRC = gw.STORE.parent.parent / "scratch" / "ladder" / "simpleqa_eval.py"


def grader_template() -> str:
    src = GRADER_SRC.read_text()
    m = re.search(r'GRADER_TEMPLATE = """(.*?)""".strip\(\)', src, re.S)
    return m.group(1).strip()


def items(n: int, seed: int = 0):
    rows = list(csv.DictReader(DATA.open()))
    random.Random(seed).shuffle(rows)
    out = []
    for i, r in enumerate(rows[:n]):
        md = ast.literal_eval(r["metadata"])
        out.append({"id": i, "q": r["problem"], "gold": r["answer"],
                    "topic": md["topic"], "type": md["answer_type"]})
    return out


def arm_name(role, effort):
    return f"{role}-{effort or 'default'}"


def parse_conf(text: str):
    m = re.findall(r"Confidence:\s*(\d{1,3})\s*%", text)
    return min(int(m[-1]), 100) if m else None


def strip_conf(text: str) -> str:
    return re.sub(r"\n?\s*Confidence:\s*\d{1,3}\s*%\s*$", "", text.strip()).strip()


def grade_one(q, gold, pred, cache, key):
    hit = cache.get(key)
    if hit:
        return hit
    p = grader_template().format(question=q, target=gold, predicted_answer=pred)
    r = gw.call("sonnet", p, max_tokens=4000, effort="low")
    if "error" in r:
        return cache.put(key, r)
    m = re.search(r"\b(A|B|C)\b", r["text"])
    r["grade"] = {"A": "CORRECT", "B": "INCORRECT", "C": "NOT_ATTEMPTED"}.get(
        m.group(1) if m else "", "UNPARSED")
    return cache.put(key, r)


def calibrate(its):
    """Known positive (gold restated), known negative (another item's gold), empty."""
    cache = gw.Cache("simpleqa-grader-calibration")
    sample = its[:20]
    jobs = []
    for i, it in enumerate(sample):
        wrong = sample[(i + 7) % len(sample)]["gold"]
        jobs += [(it, f"The answer is {it['gold']}.", "CORRECT", f"pos-{it['id']}"),
                 (it, f"The answer is {wrong}.", "INCORRECT", f"neg-{it['id']}"),
                 (it, "", "NOT_ATTEMPTED", f"empty-{it['id']}"),
                 (it, "I don't know.", "NOT_ATTEMPTED", f"idk-{it['id']}")]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: (j, grade_one(j[0]["q"], j[0]["gold"], j[1], cache, j[3])),
                          jobs))
    bad = [(j[3], j[2], r.get("grade")) for j, r in res if r.get("grade") != j[2]]
    print(f"grader calibration: {len(jobs) - len(bad)}/{len(jobs)} as expected")
    for b in bad:
        print("  MISMATCH", b)
    return bad


def run(its, workers=8):
    cache = gw.Cache("simpleqa-answers")
    jobs = [(it, role, eff) for it in its for role, eff in ARMS
            if not cache.get(f"{it['id']}|{arm_name(role, eff)}")]
    print(f"{len(jobs)} answer calls to make")

    def do(j):
        it, role, eff = j
        r = gw.call(role, PROMPT.format(q=it["q"]), max_tokens=16000, effort=eff)
        return cache.put(f"{it['id']}|{arm_name(role, eff)}", r)

    with ThreadPoolExecutor(workers) as ex:
        for k, _ in enumerate(ex.map(do, jobs)):
            if k % 100 == 0:
                print(f"  {k}/{len(jobs)}  spend ${cache.spend():.2f}", flush=True)
    print(f"answers spend ${cache.spend():.2f}")


def grade(its, workers=8):
    ans = gw.Cache("simpleqa-answers")
    gcache = gw.Cache("simpleqa-grades")
    jobs = []
    for it in its:
        for role, eff in ARMS:
            k = f"{it['id']}|{arm_name(role, eff)}"
            a = ans.get(k)
            if a and not gcache.get(k):
                jobs.append((it, strip_conf(a["text"]), k))
    print(f"{len(jobs)} grade calls to make")
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda j: grade_one(j[0]["q"], j[0]["gold"], j[1], gcache, j[2]), jobs))
    print(f"grader spend ${gcache.spend():.2f}")


def table(its):
    ans = gw.Cache("simpleqa-answers")
    g = gw.Cache("simpleqa-grades")
    rows = {}
    for it in its:
        for role, eff in ARMS:
            k = f"{it['id']}|{arm_name(role, eff)}"
            a, gr = ans.get(k), g.get(k)
            if a and gr and gr.get("grade") in ("CORRECT", "INCORRECT", "NOT_ATTEMPTED"):
                rows.setdefault(arm_name(role, eff), []).append(
                    {"id": it["id"], "grade": gr["grade"], "conf": parse_conf(a["text"]),
                     "cost": a["cost"], "latency": a["latency"],
                     "out": a["usage"]["output_tokens"]})
    return rows


def report(its):
    rows = table(its)
    out = {"n_items": len(its), "source": SRC, "arms": {}}
    for arm, rs in rows.items():
        n = len(rs)
        c = sum(r["grade"] == "CORRECT" for r in rs)
        w = sum(r["grade"] == "INCORRECT" for r in rs)
        na = n - c - w
        lat = sorted(r["latency"] for r in rs)
        out["arms"][arm] = {
            "n": n, "correct": c / n, "incorrect": w / n, "not_attempted": na / n,
            "precision_when_attempted": c / (c + w) if c + w else None,
            "cost_per_item": sum(r["cost"] for r in rs) / n,
            "median_latency_s": lat[n // 2], "p90_latency_s": lat[int(n * .9)],
            "mean_out_tokens": sum(r["out"] for r in rs) / n,
            "conf_parsed": sum(r["conf"] is not None for r in rs) / n,
            "calibration": calib_bins(rs),
        }
    out["cascades"] = cascades(rows)
    p = gw.STORE / "simpleqa-report.json"
    p.write_text(json.dumps(out, indent=1))
    for arm, a in out["arms"].items():
        print(f"{arm:16s} n={a['n']} correct={a['correct']:.3f} WRONG={a['incorrect']:.3f} "
              f"abstain={a['not_attempted']:.3f} prec={a['precision_when_attempted']:.3f} "
              f"$/item={a['cost_per_item']:.5f} med={a['median_latency_s']:.1f}s")
    for c in out["cascades"]:
        print("  cascade", c)
    print(p)


def calib_bins(rs):
    bins = [(0, 50), (50, 80), (80, 95), (95, 101)]
    out = []
    for lo, hi in bins:
        b = [r for r in rs if r["conf"] is not None and lo <= r["conf"] < hi]
        if b:
            out.append({"conf": f"{lo}-{hi - 1}", "n": len(b),
                        "correct": sum(r["grade"] == "CORRECT" for r in b) / len(b),
                        "wrong": sum(r["grade"] == "INCORRECT" for r in b) / len(b)})
    return out


def cascades(rows, small="haiku-default", big="opus-default"):
    """Escalate to `big` when `small`'s stated confidence is below t. Offline: both arms
    were answered independently on the same items, so the cascade is a selection."""
    s = {r["id"]: r for r in rows.get(small, [])}
    b = {r["id"]: r for r in rows.get(big, [])}
    ids = [i for i in s if i in b]
    out = []
    for t in (0, 50, 70, 80, 90, 95, 101):
        c = w = 0
        cost = lat = 0.0
        esc = 0
        for i in ids:
            conf = s[i]["conf"] if s[i]["conf"] is not None else 0
            cost += s[i]["cost"]
            lat += s[i]["latency"]
            pick = s[i]
            if conf < t:
                esc += 1
                cost += b[i]["cost"]
                lat += b[i]["latency"]
                pick = b[i]
            c += pick["grade"] == "CORRECT"
            w += pick["grade"] == "INCORRECT"
        n = len(ids)
        out.append({"small": small, "big": big, "escalate_below": t, "n": n,
                    "escalated": esc / n, "correct": c / n, "incorrect": w / n,
                    "cost_per_item": cost / n, "mean_latency_s": lat / n})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--grade", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    its = items(a.n)
    if a.calibrate and calibrate(its):
        sys.exit("grader failed calibration; not scoring models with it")
    if a.run:
        run(its)
    if a.grade:
        grade(its)
    if a.report:
        report(its)
