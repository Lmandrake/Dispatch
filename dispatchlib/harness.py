"""Which agent harness a task class should run on: Claude Code, Pi or OMP.

The model ladder (`tiers`) picks the model. This picks the harness that drives it, from
the per-run measurements in a local results directory (not published). Every
figure is COMPUTED from those `runs.jsonl` files at call time, never typed here, so a
re-run that changes a result changes the recommendation, and `tests/test_harness.py`
fails if a direction a rule rests on stops being true.

THE RULE, in order:

  1. Guards first. Claude Code is the only harness whose shell hooks, permission rules
     and subagents run (`harnesses/docs/FEATURES.md`); Pi and OMP run every tool without
     asking. So unless the caller says guards are not needed (a sandbox, a throwaway
     container), the answer is Claude Code, and the measured alternative is printed
     beside it. This is a feature fact, not a measurement.
  2. Success next, honestly. Pass rates are compared with 90% Wilson intervals. At n=3
     per task they almost always overlap, and overlapping means TIED, never "better".
  3. Among the tied, the class's cost metric decides (wall time, local CPU, memory or
     context sent), then operational failures (crashes, stalls).

What this does NOT do: launch a harness (owner ruling 2026-10-25: no `delegate
--harness pi` until harder results are in), or claim any ordering of task success the
data cannot support. Stdlib only; reads files, no network.
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics

REPO = pathlib.Path(__file__).resolve().parents[1]
RESULTS = REPO / "harnesses" / "results"

CLAUDE, PI, OMP = "claude-code", "pi", "omp"
HARNESSES = (CLAUDE, PI, OMP)

#: Task classes, the load-bearing runs for each (docs/CAPABILITY-*.md say which runs had
#: a defect in one arm and are kept only as evidence of it), and the cost that decides.
CLASSES = {
    "short-edit": {
        "what": "short, well-specified coding edits (suite tasks 01-10)",
        "runs": ("cap-sonnet-final-2026-10-23", "cap-haiku-final-2026-10-23",
                 "cap-sonnet-full-2026-10-24"),
        "metric": "wall_s",
    },
    "hard-coding": {
        "what": "multi-file features, races, migrations, spec work (suite tasks 11-15)",
        "runs": ("cap-sonnet-hard-2026-10-24", "cap-sonnet-full-hard-2026-10-25"),
        "metric": "wall_s",
    },
    "many-agents": {
        "what": "many concurrent agents on one laptop, mostly waiting on the model",
        "runs": ("pilot-2026-10-23",),
        "metric": "cpu_s",
    },
    "unattended": {
        "what": "a long unattended run, where a crash or a stalled stream is the cost",
        "runs": ("cap-sonnet-final-2026-10-23", "cap-haiku-final-2026-10-23",
                 "cap-sonnet-full-2026-10-24", "cap-sonnet-hard-2026-10-24",
                 "cap-sonnet-full-hard-2026-10-25"),
        "metric": "op_rate",
    },
    "metered": {
        "what": "a metered or rate-limited gateway, where context sent is the cost",
        "runs": ("cap-sonnet-final-2026-10-23", "cap-haiku-final-2026-10-23",
                 "cap-sonnet-hard-2026-10-24"),
        "metric": "context",
    },
}

METRIC_WORDS = {"wall_s": "median wall s per run", "cpu_s": "median local CPU s per run",
                "context": "median context tokens per run", "rss_mb": "median peak RSS MB",
                "op_rate": "crash-or-stall rate"}


def _fmt(x) -> str:
    if x is None:
        return "unmeasured"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"


def harness_of(arm: str) -> str | None:
    """`claude-stock`, `claude-full`, `claude-bare` -> claude-code; `pi-*` -> pi; `omp-*` -> omp."""
    head = (arm or "").split("-", 1)[0]
    return {"claude": CLAUDE, "pi": PI, "omp": OMP}.get(head)


def _rows(run: str, results: pathlib.Path) -> list[dict]:
    path = results / run / "runs.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _normalise(row: dict) -> dict | None:
    """One comparable record per harness run, from either results format.

    Capability runs carry `arm`, `passed`, `wall_s`, `cpu_s`, tokens. The CPU pilot
    carries `harness`, `profile`, `kind`, `ok`, `rusage_cpu_s`; only its headless runs
    are one task each, so only those are used.
    """
    if "arm" in row:
        h = harness_of(row["arm"])
        ctx = sum(row.get(k) or 0 for k in ("in", "cache_read", "cache_write"))
        operational = bool(row.get("timed_out")) or (row.get("rc") not in (0, None)
                                                     and not row.get("passed"))
        return h and {"harness": h, "passed": bool(row.get("passed")),
                      "operational_failure": operational, "wall_s": row.get("wall_s"),
                      "cpu_s": row.get("cpu_s"), "rss_mb": row.get("peak_rss_mb"),
                      "context": ctx or None}
    if row.get("kind") == "headless" and "harness" in row:
        h = harness_of(row["harness"])
        return h and {"harness": h, "passed": bool(row.get("ok")),
                      "operational_failure": not row.get("ok"), "wall_s": row.get("wall_s"),
                      "cpu_s": row.get("rusage_cpu_s"), "rss_mb": row.get("peak_tree_rss_mb"),
                      "context": None}
    return None


def wilson(k: int, n: int, z: float = 1.645) -> tuple[float, float]:
    """90% Wilson interval for k successes in n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def evidence(task_class: str, results: pathlib.Path = RESULTS) -> dict:
    """Per-harness numbers for one class, pooled over its load-bearing runs."""
    spec = CLASSES[task_class]
    if results == RESULTS and not results.is_dir():
        # Per-run data is not published; use the committed per-class summary.
        saved = json.loads(pathlib.Path(__file__).with_name("harness_summary.json").read_text())[task_class]
        for v in saved["by_harness"].values():
            if "pass_ci90" in v:
                v["pass_ci90"] = tuple(v["pass_ci90"])
        saved["sources"] = ["docs/MEASURED_RESULTS.md"]
        return saved
    pooled: dict[str, list[dict]] = {h: [] for h in HARNESSES}
    sources = []
    for run in spec["runs"]:
        sources.append(str((results / run / "runs.jsonl").relative_to(REPO))
                       if results == RESULTS else str(results / run / "runs.jsonl"))
        for raw in _rows(run, results):
            rec = _normalise(raw)
            if rec:
                pooled[rec["harness"]].append(rec)
    out = {}
    for h, recs in pooled.items():
        if not recs:
            continue
        k = sum(r["passed"] for r in recs)

        def med(key):
            xs = [r[key] for r in recs if r.get(key) is not None]
            return statistics.median(xs) if xs else None
        out[h] = {"n": len(recs), "passed": k, "pass_ci90": wilson(k, len(recs)),
                  "operational_failures": sum(r["operational_failure"] for r in recs),
                  "wall_s": med("wall_s"), "cpu_s": med("cpu_s"), "rss_mb": med("rss_mb"),
                  "context": med("context"),
                  "op_rate": sum(r["operational_failure"] for r in recs) / len(recs)}
    return {"class": task_class, "what": spec["what"], "metric": spec["metric"],
            "sources": sources, "by_harness": out}


def _tied_with_best(by: dict) -> list[str]:
    """Harnesses whose 90% pass interval overlaps the best harness's interval."""
    best = max(by, key=lambda h: by[h]["passed"] / by[h]["n"])
    lo_best = by[best]["pass_ci90"][0]
    return [h for h in by if by[h]["pass_ci90"][1] >= lo_best]


def recommend(task_class: str, *, guards_needed: bool = True,
              results: pathlib.Path = RESULTS) -> dict:
    """The harness for one task class, with the evidence and the reasoning.

    Returns {class, harness, measured_choice, guards_needed, tied, metric, reason,
    evidence}. `measured_choice` is what the measurements alone pick; `harness` is what
    to run once rule 1 (guards) is applied.
    """
    if task_class not in CLASSES:
        raise ValueError(f"task class must be one of {tuple(CLASSES)}, got {task_class!r}")
    ev = evidence(task_class, results)
    by = ev["by_harness"]
    metric = ev["metric"]
    tied = _tied_with_best(by)
    costed = [h for h in tied if by[h].get(metric) is not None]
    measured = min(costed, key=lambda h: (by[h][metric], by[h]["operational_failures"]))
    m = by[measured]
    why = (f"pass rates tied within 90% intervals ({', '.join(sorted(tied))}); "
           f"{measured} has the lowest {METRIC_WORDS[metric]} "
           f"({_fmt(m[metric])}) among them")
    if guards_needed and measured != CLAUDE:
        harness = CLAUDE
        c = by.get(CLAUDE, {})
        reason = (f"guards needed: only Claude Code runs the hooks and permission rules. "
                  f"Without that constraint the measurements pick {measured}: {why}; "
                  f"Claude Code's {METRIC_WORDS[metric]} is {_fmt(c.get(metric))}")
    else:
        harness = measured
        reason = why
    return {"class": task_class, "harness": harness, "measured_choice": measured,
            "guards_needed": guards_needed, "tied": sorted(tied), "metric": metric,
            "reason": reason, "evidence": ev}
