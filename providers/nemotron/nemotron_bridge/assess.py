"""Assessment orchestrator: run perf + the task battery against models.

Captures objective metrics (via metrics.py) and saves every raw output to disk
so the judge stage (judge.py) can score them later. Nothing here calls a judge —
this stage is deterministic and re-runnable.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config
from .client import NemotronClient, vision_message
from .metrics import measure_perf, probe_max_rate
from .registry import Registry

BATTERY_FILE = config.BATTERY_DIR / "tasks.yaml"
ASSETS_DIR = config.BATTERY_DIR / "assets"


def slug(model_id: str) -> str:
    return model_id.replace("/", "__")


def load_battery() -> list[dict]:
    data = yaml.safe_load(BATTERY_FILE.read_text())
    return data["tasks"]


def ensure_vision_asset() -> Path:
    """Generate a deterministic test chart image if it doesn't exist."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSETS_DIR / "chart.png"
    if path.exists():
        return path
    from PIL import Image, ImageDraw

    w, h = 480, 320
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    # axes
    d.line([(50, 280), (450, 280)], fill="black", width=2)
    d.line([(50, 280), (50, 30)], fill="black", width=2)
    # rising line through labeled points
    pts = [(50, 260), (150, 210), (250, 150), (350, 90), (430, 50)]
    d.line(pts, fill="blue", width=3)
    labels = ["10", "25", "40", "60", "80"]
    for (x, y), lab in zip(pts, labels):
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill="red")
        d.text((x - 6, y - 20), lab, fill="black")
    d.text((180, 295), "Quarter (Q1..Q5)", fill="black")
    img.save(path)
    return path


def run_assessment(
    model_ids: list[str],
    repeats: int = 3,
    rate_probe: bool = True,
    run_dir: Path | None = None,
    timeout: float = 120.0,
    model_budget: float = 360.0,
) -> Path:
    """Assess each model. `timeout` caps a single call; `model_budget` caps total
    wall time per model so one cold/dead model can't stall an unattended sweep —
    remaining tasks for a model are skipped once its budget is exceeded."""
    reg = Registry.load()
    tasks = load_battery()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = run_dir or (config.RESULTS_DIR / f"run-{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)

    client = NemotronClient(timeout=timeout)
    need_vision = any(
        reg.get(m) and reg.get(m).modality == "vision" for m in model_ids
    )
    vision_img = ensure_vision_asset() if need_vision else None

    meta = {
        "started": stamp,
        "models": model_ids,
        "repeats": repeats,
        "battery_tasks": [t["id"] for t in tasks],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    for mid in model_ids:
        entry = reg.get(mid)
        modality = entry.modality if entry else "chat"
        mdir = run_dir / slug(mid)
        (mdir / "tasks").mkdir(parents=True, exist_ok=True)
        model_start = time.monotonic()
        print(f"\n=== {mid}  [{modality}] ===")

        # Perf (short prompt, N repeats).
        perf = measure_perf(client, mid, repeats=repeats)
        (mdir / "metrics.json").write_text(json.dumps(perf.as_dict(), indent=2))
        print(
            f"  perf: ttft={perf.ttft_median}s  tok/s={perf.tokens_per_sec_median}  "
            f"lat={perf.latency_median}s  ok={perf.ok}/{perf.runs}"
        )

        # Rate probe (optional; costs a burst of tiny calls).
        if rate_probe:
            rp = probe_max_rate(mid)
            (mdir / "rate.json").write_text(json.dumps(rp.as_dict(), indent=2))
            print(
                f"  rate: {rp.successes} ok / {rp.rate_limited} 429 in {rp.elapsed}s "
                f"(~{rp.effective_rpm} rpm)"
            )

        # Battery.
        for task in tasks:
            if modality not in task.get("modality", ["chat"]):
                continue
            tid = task["id"]
            if time.monotonic() - model_start > model_budget:
                print(f"  task {tid:22} SKIPPED (model time budget {model_budget}s exceeded)")
                (mdir / "tasks" / f"{tid}.json").write_text(
                    json.dumps(
                        {
                            "task_id": tid,
                            "category": task["category"],
                            "criteria": task["criteria"],
                            "prompt": task["prompt"],
                            "output": "",
                            "ok": False,
                            "error": "skipped: model time budget exceeded",
                            "skipped": True,
                        },
                        indent=2,
                    )
                )
                continue
            if "image" in task and vision_img is not None:
                messages = [vision_message(task["prompt"], vision_img)]
            else:
                messages = [{"role": "user", "content": task["prompt"]}]
            r = client.chat(
                mid,
                messages,
                max_tokens=task.get("max_tokens", 800),
                stream=True,
            )
            truncated = bool(r.ok and not r.text and r.had_reasoning)
            (mdir / "tasks" / f"{tid}.json").write_text(
                json.dumps(
                    {
                        "task_id": tid,
                        "category": task["category"],
                        "criteria": task["criteria"],
                        "prompt": task["prompt"],
                        "output": r.text,
                        "ok": r.ok,
                        "error": r.error,
                        "ttft": r.ttft,
                        "latency": r.latency,
                        "completion_tokens": r.completion_tokens,
                        "had_reasoning": r.had_reasoning,
                        "reasoning_chars": r.reasoning_chars,
                        "truncated_reasoning_only": truncated,
                    },
                    indent=2,
                )
            )
            if truncated:
                status = "TRUNCATED(reasoning-only, no answer in budget)"
            elif r.ok and r.text:
                status = "ok"
            else:
                status = f"FAIL({r.error})"
            print(f"  task {tid:22} {status}")

    print(f"\nRun complete → {run_dir}")
    return run_dir
