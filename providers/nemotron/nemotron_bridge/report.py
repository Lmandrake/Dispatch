"""Reporting: turn a judged run into human-readable scorecards + a leaderboard.

Produces:
  * results/scorecards/<model>.md — one card per model (perf + quality + tier)
  * <run_dir>/leaderboard.md and results/leaderboard.md — ranked comparison
  * <run_dir>/leaderboard.json — machine-readable, consumed by the routing skill
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .registry import Registry


def _load(mdir: Path, name: str) -> dict:
    p = mdir / name
    return json.loads(p.read_text()) if p.exists() else {}


def _task_health(mdir: Path) -> dict:
    """Summarize battery outcomes, distinguishing three failure modes:
      * answered (ok)         — usable
      * truncated / skipped   — reachable but slow (budget/timeout capped)
      * 404 / hard error      — not callable on the free tier (unavailable)
    so a slow model isn't mislabeled as unavailable, and neither drags down a
    quality verdict."""
    files = sorted((mdir / "tasks").glob("*.json"))
    n = ok = trunc = skipped = notfound = other_err = 0
    error_types: set[str] = set()
    for f in files:
        t = json.loads(f.read_text())
        n += 1
        err = (t.get("error") or "")
        if t.get("truncated_reasoning_only"):
            trunc += 1
        elif t.get("ok") and t.get("output"):
            ok += 1
        elif t.get("skipped") or "skipped" in err.lower():
            skipped += 1
        elif "404" in err or "NotFound" in err:
            notfound += 1
            error_types.add("NotFound")
        elif not t.get("ok"):
            other_err += 1
            error_types.add((err or "error").split(":")[0].split(" ")[0] or "error")

    reachable = ok + trunc + skipped          # got some kind of response/timeout
    if ok >= 1 and ok >= (notfound + other_err):
        status = "ok"                          # produced real answers
    elif notfound + other_err >= max(1, n // 2) and ok == 0:
        status = "unavailable"                 # 404/hard-errored, never answered
    elif reachable > 0 and ok == 0:
        status = "slow"                        # reachable but capped out every task
    elif ok >= 1:
        status = "ok"
    else:
        status = "unavailable"
    return {
        "n_tasks": n,
        "n_ok": ok,
        "n_truncated": trunc,
        "n_skipped": skipped,
        "n_error": notfound + other_err,
        "availability": round(ok / n, 2) if n else 0.0,
        "error_types": sorted(error_types),
        "status": status,
        "available": status == "ok",
    }


def _fmt(v, suffix="") -> str:
    return f"{v}{suffix}" if v is not None else "—"


def build_scorecard(mdir: Path, reg: Registry) -> dict:
    model_id = mdir.name.replace("__", "/")
    metrics = _load(mdir, "metrics.json")
    rate = _load(mdir, "rate.json")
    scores = _load(mdir, "scores.json")
    health = _task_health(mdir)
    entry = reg.get(model_id)

    tier = scores.get("tier")
    if not health["available"]:
        tier = "unavailable"

    card = {
        "model": model_id,
        "modality": entry.modality if entry else "chat",
        "owner": entry.owner if entry else model_id.split("/")[0],
        "ttft_s": metrics.get("ttft_median"),
        "tokens_per_sec": metrics.get("tokens_per_sec_median"),
        "latency_s": metrics.get("latency_median"),
        "perf_ok": f"{metrics.get('ok', 0)}/{metrics.get('runs', 0)}",
        "effective_rpm": rate.get("effective_rpm"),
        "rate_limited": rate.get("rate_limited"),
        "overall": scores.get("overall"),
        "category_avg": scores.get("category_avg", {}),
        "tier": tier,
        "tier_confidence": scores.get("tier_confidence"),
        "tier_rationale": scores.get("tier_rationale"),
        "available": health["available"],
        "status": health["status"],
        "availability": health["availability"],
        "n_ok": health["n_ok"],
        "n_tasks": health["n_tasks"],
        "n_truncated": health["n_truncated"],
        "n_skipped": health["n_skipped"],
        "n_error": health["n_error"],
        "error_types": health["error_types"],
    }

    md = f"""# Scorecard — `{model_id}`

**Modality:** {card['modality']}  ·  **Owner:** {card['owner']}  ·  **Nearest Anthropic tier:** {_fmt(card['tier'])} ({_fmt(card['tier_confidence'])} confidence)

## Performance
| Metric | Value |
|---|---|
| Time to first token (median) | {_fmt(card['ttft_s'], ' s')} |
| Velocity (decode tokens/sec, median) | {_fmt(card['tokens_per_sec'])} |
| Total latency (median) | {_fmt(card['latency_s'], ' s')} |
| Perf runs succeeded | {card['perf_ok']} |
| Empirical burst rate | {_fmt(card['effective_rpm'], ' rpm')} ({_fmt(card['rate_limited'])} rate-limited) |

## Battery health
| | |
|---|---|
| Tasks answered | {card['n_ok']}/{card['n_tasks']} (availability {card['availability']}) |
| Truncated (reasoning-only, no answer) | {card['n_truncated']} |
| Errored | {card['n_error']} {card['error_types'] or ''} |
| Available for real work | {'yes' if card['available'] else 'NO — errored on most tasks'} |

## Quality (0–10, judged)
**Overall: {_fmt(card['overall'])}/10**{'  _(scores unreliable — model errored)_' if not card['available'] else ''}

| Category | Score |
|---|---|
"""
    for cat, val in sorted(card["category_avg"].items()):
        md += f"| {cat} | {val} |\n"
    md += f"\n**Tier rationale:** {_fmt(card['tier_rationale'])}\n"

    config.SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    (config.SCORECARD_DIR / f"{mdir.name}.md").write_text(md)
    (mdir / "scorecard.md").write_text(md)
    return card


_TIER_RANK = {"~Opus": 3, "~Sonnet": 2, "~Haiku": 1, "below-Haiku": 0, None: -1}


def _render_leaderboard(cards: list[dict], title_note: str) -> str:
    available = [c for c in cards if c.get("status") == "ok"]
    slow = [c for c in cards if c.get("status") == "slow"]
    unavailable = [c for c in cards if c.get("status") == "unavailable"]
    cards_sorted = sorted(
        available,
        key=lambda c: (c.get("overall") or 0, _TIER_RANK.get(c.get("tier"), -1)),
        reverse=True,
    )

    md = "# Nemotron Bridge — Model Leaderboard\n\n"
    md += title_note + "\n\n"
    md += "| Rank | Model | Tier | Quality | Answered | tok/s | TTFT (s) | Modality |\n"
    md += "|---|---|---|---|---|---|---|---|\n"
    for i, c in enumerate(cards_sorted, 1):
        answered = f"{c['n_ok']}/{c['n_tasks']}"
        if c["n_truncated"]:
            answered += f" (+{c['n_truncated']} trunc)"
        md += (
            f"| {i} | `{c['model']}` | {_fmt(c['tier'])} | {_fmt(c['overall'])} | "
            f"{answered} | {_fmt(c['tokens_per_sec'])} | {_fmt(c['ttft_s'])} | {c['modality']} |\n"
        )
    md += "\n## Category leaders\n\n"
    cats: set[str] = set()
    for c in available:
        cats.update(c["category_avg"].keys())
    for cat in sorted(cats):
        ranked = sorted(
            (c for c in available if cat in c["category_avg"]),
            key=lambda c: c["category_avg"][cat],
            reverse=True,
        )
        if ranked:
            top = ranked[0]
            md += f"- **{cat}** → `{top['model']}` ({top['category_avg'][cat]}/10)\n"

    if slow:
        md += f"\n## Reachable but too slow to score — {len(slow)} models\n\n"
        md += (
            "These responded but exhausted the per-model time budget (heavy reasoning "
            "or slow decode), so the battery couldn't complete. Usable for latency-"
            "tolerant batch work; raise `--budget`/`--timeout` to score them.\n\n"
        )
        for c in sorted(slow, key=lambda c: c["model"]):
            md += (
                f"- `{c['model']}` — {c['n_ok']}/{c['n_tasks']} answered, "
                f"{c['n_skipped']} capped · tok/s {_fmt(c['tokens_per_sec'])}\n"
            )

    if unavailable:
        md += f"\n## Unavailable on the free tier — {len(unavailable)} models (not ranked)\n\n"
        md += (
            "Listed in the catalog but not usably callable during assessment (mostly "
            "404 'function not found'). An availability issue, not a quality verdict.\n\n"
        )
        for c in sorted(unavailable, key=lambda c: c["model"]):
            md += f"- `{c['model']}` — {c['n_error']}/{c['n_tasks']} errored {c['error_types']}\n"
    return md


def build_leaderboard(run_dir: Path) -> Path:
    reg = Registry.load()
    model_dirs = [d for d in run_dir.iterdir() if d.is_dir() and (d / "tasks").exists()]
    cards = [build_scorecard(d, reg) for d in sorted(model_dirs)]
    note = (
        "Ranked by judged quality (0–10) across a compact battery. Velocity = decode "
        "tokens/sec. Free tier ~40 RPM. Tiers are rough qualitative anchors, not "
        "benchmark claims — the judge is lenient, so treat close scores as ties."
    )
    md = _render_leaderboard(cards, note)
    (run_dir / "leaderboard.md").write_text(md)
    (run_dir / "leaderboard.json").write_text(json.dumps(cards, indent=2))
    print(f"Leaderboard → {run_dir / 'leaderboard.md'}")
    return run_dir / "leaderboard.md"


def build_master_leaderboard(results_dir: Path = config.RESULTS_DIR) -> Path:
    """Aggregate every run into one deduped leaderboard.

    When a model was assessed in multiple runs, keep the best record: prefer
    available over unavailable, then higher availability, then more recent run.
    """
    reg = Registry.load()
    best: dict[str, tuple] = {}  # model -> (rank_key, mdir)
    _status_rank = {"ok": 2, "slow": 1, "unavailable": 0}
    for run in sorted(results_dir.glob("run-*")):
        mtime = run.stat().st_mtime
        for mdir in run.iterdir():
            if not (mdir.is_dir() and (mdir / "tasks").exists()):
                continue
            model = mdir.name.replace("__", "/")
            health = _task_health(mdir)
            has_scores = (mdir / "scores.json").exists()
            # Prefer: better status, then judged, then more answers, then recency.
            key = (
                _status_rank.get(health["status"], 0),
                1 if has_scores else 0,
                health["n_ok"],
                mtime,
            )
            if model not in best or key > best[model][0]:
                best[model] = (key, mdir)

    cards = [build_scorecard(mdir, reg) for _, mdir in sorted(best.values(), key=lambda x: str(x[1]))]
    note = (
        f"**Master leaderboard — {len([c for c in cards if c.get('available')])} usable "
        f"of {len(cards)} models assessed** across all runs. Ranked by judged quality "
        "(0–10). Velocity = decode tokens/sec. Free tier ~40 RPM. Tiers are rough "
        "qualitative anchors (lenient judge — treat close scores as ties). Many catalog "
        "models are unavailable on the free tier (see bottom)."
    )
    md = _render_leaderboard(cards, note)
    (results_dir / "leaderboard.md").write_text(md)
    (results_dir / "leaderboard.json").write_text(json.dumps(cards, indent=2))
    print(f"Master leaderboard → {results_dir / 'leaderboard.md'} ({len(cards)} models)")
    return results_dir / "leaderboard.md"
