"""Judge stage: score saved battery outputs against the rubric.

Default judge is a strong *free* peer model (no Anthropic tokens spent), which
keeps the whole assessment self-contained. Pass a different `--judge-model` to
use another. A `judge_manifest.json` is also written so a human or Claude can
re-score by hand later.

Outputs per model: `scores.json` with per-task scores + an aggregate
nearest-Anthropic tier.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from . import config
from .client import NemotronClient

# A strong, reliable, *non-reasoning* instruction-follower makes the best judge:
# it returns clean JSON without burning the token budget on hidden reasoning.
DEFAULT_JUDGE = "meta/llama-3.3-70b-instruct"
RUBRIC_PATH = config.BATTERY_DIR / "rubric.md"

_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Best-effort: pull the last JSON object out of a model response."""
    if not text:
        return None
    candidates = _JSON_RE.findall(text)
    for cand in reversed(candidates):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    # try fenced blocks
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for cand in reversed(fenced):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def _score_prompt(task: dict, rubric: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "You are a strict, fair grader. Return only the requested JSON.",
        },
        {
            "role": "user",
            "content": (
                f"{rubric}\n\n"
                "---\nGrade THIS task now. Return only the per-task JSON "
                '(`{"score": int, "reason": str}`).\n\n'
                f"TASK PROMPT:\n{task['prompt']}\n\n"
                f"SUCCESS CRITERIA:\n{task['criteria']}\n\n"
                f"MODEL OUTPUT:\n{task['output'] or '(empty)'}\n"
            ),
        },
    ]


def _tier_prompt(model_id: str, scored: list[dict], rubric: str) -> list[dict]:
    summary = "\n".join(
        f"- {s['task_id']} ({s['category']}): {s['score']}/10 — {s['reason']}"
        for s in scored
    )
    return [
        {"role": "system", "content": "You map model capability to Anthropic tiers. Return only JSON."},
        {
            "role": "user",
            "content": (
                f"{rubric}\n\n---\nModel `{model_id}` per-task results:\n{summary}\n\n"
                "Now return only the nearest-Anthropic-tier JSON "
                '(`{"tier": str, "confidence": str, "rationale": str}`).'
            ),
        },
    ]


def judge_run(
    run_dir: Path,
    judge_model: str = DEFAULT_JUDGE,
    client: NemotronClient | None = None,
) -> None:
    client = client or NemotronClient()
    rubric = RUBRIC_PATH.read_text()
    manifest = []

    model_dirs = [d for d in run_dir.iterdir() if d.is_dir() and (d / "tasks").exists()]
    for mdir in sorted(model_dirs):
        model_id = mdir.name.replace("__", "/")
        task_files = sorted((mdir / "tasks").glob("*.json"))
        scored = []
        for tf in task_files:
            task = json.loads(tf.read_text())
            manifest.append({"model": model_id, **task})
            jr = client.chat(
                judge_model, _score_prompt(task, rubric), max_tokens=1024, temperature=0.0
            )
            parsed = _extract_json(jr.text) or {}
            score = parsed.get("score")
            try:
                score = int(score)
            except (TypeError, ValueError):
                score = 0
            scored.append(
                {
                    "task_id": task["task_id"],
                    "category": task["category"],
                    "score": max(0, min(10, score)),
                    "reason": str(parsed.get("reason", ""))[:200],
                }
            )
            print(f"  judge {model_id:40} {task['task_id']:22} {scored[-1]['score']}/10")

        # Aggregate by category + overall.
        by_cat: dict[str, list[int]] = defaultdict(list)
        for s in scored:
            by_cat[s["category"]].append(s["score"])
        cat_avg = {c: round(statistics.mean(v), 2) for c, v in by_cat.items()}
        overall = round(statistics.mean([s["score"] for s in scored]), 2) if scored else 0.0

        # Nearest-Anthropic tier.
        tj = client.chat(judge_model, _tier_prompt(model_id, scored, rubric),
                         max_tokens=1024, temperature=0.0)
        tier = _extract_json(tj.text) or {}

        (mdir / "scores.json").write_text(
            json.dumps(
                {
                    "model": model_id,
                    "judge_model": judge_model,
                    "overall": overall,
                    "category_avg": cat_avg,
                    "tier": tier.get("tier"),
                    "tier_confidence": tier.get("confidence"),
                    "tier_rationale": tier.get("rationale"),
                    "tasks": scored,
                },
                indent=2,
            )
        )
        print(f"  => {model_id}: overall {overall}/10, tier {tier.get('tier')}")

    (run_dir / "judge_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nJudging complete → {run_dir}")
