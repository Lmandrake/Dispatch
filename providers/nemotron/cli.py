#!/usr/bin/env python3
"""Nemotron Bridge CLI.

Commands:
  nemo models   [--refresh]                 list / reconcile the registry
  nemo call     MODEL "prompt" [--max N]     one-off chat (for scripts + the skill)
  nemo assess   [--models ... | --preset X]  run perf + battery, save outputs
  nemo judge    RUN_DIR [--judge-model M]    score a run
  nemo report   RUN_DIR                      build scorecards + leaderboard
  nemo all      [--preset X]                 assess + judge + report in one shot
  nemo agentic  [--models ... | --preset X]  multi-turn tool-calling competence
  nemo profile  [--probe N]                  uptime/latency/error profiles per model

Presets live in battery/presets.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

from nemotron_bridge import config
from nemotron_bridge.assess import run_assessment
from nemotron_bridge.client import NemotronClient
from nemotron_bridge.judge import DEFAULT_JUDGE, judge_run
from nemotron_bridge.registry import Registry
from nemotron_bridge.report import build_leaderboard, build_master_leaderboard

PRESETS_FILE = config.BATTERY_DIR / "presets.yaml"


def _presets() -> dict:
    if PRESETS_FILE.exists():
        return yaml.safe_load(PRESETS_FILE.read_text()) or {}
    return {}


def _resolve_models(args) -> list[str]:
    reg = Registry.load()
    if getattr(args, "models", None):
        return args.models
    preset = getattr(args, "preset", None)
    if preset:
        presets = _presets()
        if preset not in presets:
            sys.exit(f"Unknown preset '{preset}'. Available: {list(presets)}")
        return presets[preset]
    return [e.id for e in reg.assessable()]


def cmd_models(args):
    reg = Registry.load()
    if args.refresh:
        added, total = reg.refresh_from_live()
        reg.save()
        print(f"Registry refreshed: +{added} new, {total} live, {len(reg.entries)} total")
    mods = {}
    for e in reg.entries.values():
        mods.setdefault(e.modality, []).append(e.id)
    for modality in sorted(mods):
        print(f"\n[{modality}] ({len(mods[modality])})")
        for mid in sorted(mods[modality]):
            print(f"  {mid}")


def cmd_call(args):
    client = NemotronClient()
    r = client.chat(
        args.model,
        [{"role": "user", "content": args.prompt}],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        stream=False,
    )
    if not r.ok:
        sys.exit(f"ERROR: {r.error}")
    if args.json:
        print(json.dumps({"text": r.text, "latency": r.latency,
                          "tokens": r.completion_tokens}, indent=2))
    else:
        print(r.text)


def cmd_assess(args):
    models = _resolve_models(args)
    print(f"Assessing {len(models)} model(s): {', '.join(models)}")
    run_dir = run_assessment(
        models, repeats=args.repeats, rate_probe=not args.no_rate,
        timeout=args.timeout, model_budget=args.budget,
    )
    print(run_dir)


def cmd_judge(args):
    judge_run(Path(args.run_dir), judge_model=args.judge_model)


def cmd_report(args):
    build_leaderboard(Path(args.run_dir))


def cmd_leaderboard(args):
    build_master_leaderboard()


def _open_file(path: Path) -> None:
    """Open a file in the OS default app (macOS/Windows/Linux)."""
    import subprocess
    import sys as _sys
    try:
        if _sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif _sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


def cmd_image(args):
    """Generate a pixel image with FLUX (free) and optionally open it."""
    client = NemotronClient()
    size = args.size
    out = Path(args.out) if args.out else (
        config.RESULTS_DIR / "graphics" / "generated"
        / (re.sub(r"[^a-z0-9]+", "-", args.prompt.lower())[:40].strip("-") + ".png")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    steps = 4 if ("schnell" in args.model or "klein" in args.model) else args.steps
    print(f"Generating [{args.model}] {size}x{size} steps={steps}: {args.prompt!r}")
    r = client.generate_image(args.model, args.prompt, width=size, height=size,
                              steps=steps, seed=args.seed)
    if not r.ok:
        sys.exit(f"ERROR: {r.error}")
    out.write_bytes(r.image)
    print(f"saved {out}  ({r.latency:.1f}s, {r.width}x{r.height})")
    if args.open:
        _open_file(out)


def cmd_where(args):
    """Print repo location + key artifact paths (portable; no hardcoded paths)."""
    from nemotron_bridge.config import get_api_key, redact, MissingKeyError
    root = config.REPO_ROOT
    try:
        key_status = redact(get_api_key())
    except MissingKeyError:
        key_status = "NOT SET (export NVIDIA_API_KEY)"
    info = {
        "repo_root": str(root),
        "leaderboard": str(config.RESULTS_DIR / "leaderboard.md"),
        "wisdom": str(root / "WISDOM.md"),
        "registry": str(config.REGISTRY_PATH),
        "api_key": key_status,
    }
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        for k, v in info.items():
            print(f"{k:12} {v}")


def cmd_graphics(args):
    from nemotron_bridge.graphics import run_graphics

    reg = Registry.load()
    if args.models:
        image_models = args.models
    else:
        image_models = [e.id for e in reg.by_modality("image-gen")
                        if e.endpoint == "genai" and "kontext" not in e.id]  # kontext needs input image
    # Find the text run with the most SVG outputs to score with the vision judge.
    svg_dir = None
    best = -1
    for run in config.RESULTS_DIR.glob("run-*"):
        n = len(list(run.glob("*/tasks/creative_svg.json")))
        if n > best:
            best, svg_dir = n, run
    print(f"Graphics: image models={image_models}; SVGs from {svg_dir} ({best})")
    run_graphics(image_models, svg_run_dir=svg_dir if not args.no_svg else None,
                 vlm=args.vlm, steps=args.steps)


def cmd_profile(args):
    """Behaviour profiles rolled up from the observation ledger."""
    from nemotron_bridge import telemetry

    if args.probe:
        # Deliberate sampling to thicken the ledger for named models. Ordinary
        # use already feeds it; this is for when you need an answer now.
        client = NemotronClient(timeout=45)
        models = _resolve_models(args)
        print(f"Probing {len(models)} model(s) x{args.probe}...")
        for mid in models:
            for _ in range(args.probe):
                client.chat(mid, [{"role": "user", "content": "hi"}],
                            max_tokens=64, stream=False)
        print("done")

    profs = telemetry.all_profiles(args.models or None)
    if not profs:
        sys.exit("No observations yet. Run any nemo command, or: nemo profile --probe 5")
    if args.json:
        print(json.dumps(profs, indent=2))
        return
    for p_ in profs:
        u = p_["uptime"]
        print(f"{p_['model']:<42} {p_['verdict']:<26} "
              f"24h={u['24h']['ok_pct'] if u['24h']['ok_pct'] is not None else '—'}% "
              f"all={p_['ok_pct_all']}% (n={p_['observations']})")
    out = telemetry.build_report(args.models or None)
    print(f"\n{out}")


def cmd_agentic(args):
    """Measure tool-calling / agentic competence (separate from chat quality)."""
    from nemotron_bridge.agentic import run_agentic_suite

    models = _resolve_models(args)
    print(f"Agentic tool-loop assessment of {len(models)} model(s)")
    run_agentic_suite(
        models,
        corpus_dir=Path(args.corpus) if args.corpus else None,
        max_turns=args.max_turns,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        model_budget=args.budget,
        repeats=args.repeats,
    )


def cmd_all(args):
    models = _resolve_models(args)
    print(f"Full assessment of {len(models)} model(s)")
    run_dir = run_assessment(
        models, repeats=args.repeats, rate_probe=not args.no_rate,
        timeout=args.timeout, model_budget=args.budget,
    )
    judge_run(run_dir, judge_model=args.judge_model)
    build_leaderboard(run_dir)
    print(f"\nDone. See {run_dir}/leaderboard.md")


def main():
    p = argparse.ArgumentParser(prog="nemo", description="Nemotron Bridge CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("models"); m.add_argument("--refresh", action="store_true")
    m.set_defaults(func=cmd_models)

    c = sub.add_parser("call")
    c.add_argument("model"); c.add_argument("prompt")
    c.add_argument("--max-tokens", type=int, default=1024)
    c.add_argument("--temperature", type=float, default=0.2)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_call)

    for name in ("assess", "all"):
        a = sub.add_parser(name)
        a.add_argument("--models", nargs="+")
        a.add_argument("--preset")
        a.add_argument("--repeats", type=int, default=3)
        a.add_argument("--no-rate", action="store_true")
        a.add_argument("--timeout", type=float, default=120.0,
                       help="per-call timeout (s)")
        a.add_argument("--budget", type=float, default=360.0,
                       help="per-model wall-clock budget (s); remaining tasks skipped past it")
        a.add_argument("--judge-model", default=DEFAULT_JUDGE)
        a.set_defaults(func=cmd_all if name == "all" else cmd_assess)

    j = sub.add_parser("judge")
    j.add_argument("run_dir"); j.add_argument("--judge-model", default=DEFAULT_JUDGE)
    j.set_defaults(func=cmd_judge)

    r = sub.add_parser("report")
    r.add_argument("run_dir")
    r.set_defaults(func=cmd_report)

    lb = sub.add_parser("leaderboard")  # master: aggregate all runs, deduped
    lb.set_defaults(func=cmd_leaderboard)

    w = sub.add_parser("where")  # print repo + artifact paths (portable)
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_where)

    im = sub.add_parser("image")  # generate a pixel image with FLUX (free)
    im.add_argument("prompt")
    im.add_argument("--model", default="black-forest-labs/flux.1-dev")  # also flux.2-klein-4b (1-2s, steps<=4)
    im.add_argument("--out", help="output PNG path")
    im.add_argument("--size", type=int, default=1024, choices=[768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280, 1344])
    im.add_argument("--steps", type=int, default=30)
    im.add_argument("--seed", type=int, default=0)
    im.add_argument("--open", action="store_true", help="open the image when done")
    im.set_defaults(func=cmd_image)

    pr = sub.add_parser("profile")  # behaviour profiles from the observation ledger
    pr.add_argument("--models", nargs="+")
    pr.add_argument("--preset")
    pr.add_argument("--probe", type=int, metavar="N",
                    help="first make N extra calls per model to thicken the ledger")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_profile)

    ag = sub.add_parser("agentic")  # multi-turn tool-calling competence
    ag.add_argument("--models", nargs="+")
    ag.add_argument("--preset", default="agentic")
    ag.add_argument("--corpus", help="score against a custom doc tree instead of the "
                                     "frozen fixture (protocol metrics only)")
    ag.add_argument("--max-turns", type=int, default=12)
    ag.add_argument("--repeats", type=int, default=3,
                    help="runs per model; termination is non-deterministic, n=1 misleads")
    ag.add_argument("--max-tokens", type=int, default=3000,
                    help="per-turn ceiling; reasoning models need headroom")
    ag.add_argument("--timeout", type=float, default=120.0)
    ag.add_argument("--budget", type=float, default=420.0,
                    help="per-model wall-clock budget (s); slow decode is itself a failure")
    ag.set_defaults(func=cmd_agentic)

    g = sub.add_parser("graphics")  # image-gen + SVG render, scored by a vision model
    g.add_argument("--models", nargs="+", help="image-gen model ids (default: registered FLUX)")
    g.add_argument("--vlm", default="meta/llama-3.2-90b-vision-instruct", help="vision judge")
    g.add_argument("--steps", type=int, default=25)
    g.add_argument("--no-svg", action="store_true", help="skip scoring chat-model SVGs")
    g.set_defaults(func=cmd_graphics)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
