"""Graphics production: real, sighted evaluation.

Two kinds of "graphics" a free model might produce:
  * raster / pixel imagery — text-to-image models on the genai host (FLUX family)
  * vector — chat models emitting SVG markup

Both are evaluated by *rendering the actual picture* and having a **vision model**
score it against the prompt — fixing the blind text-judge that rated an SVG of a
mountain range 10/10 for "paper airplane".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .client import NemotronClient, image_data_url
from .judge import _extract_json

DEFAULT_VLM = "meta/llama-3.2-90b-vision-instruct"

# Prompts used for image-generation models (varied to probe capability).
IMAGE_PROMPTS = [
    {"id": "paper_airplane",
     "prompt": "a stylized red paper airplane on a plain white background, minimalist",
     "criteria": "A recognizable red paper airplane on a plain/white background."},
    {"id": "cat_astronaut",
     "prompt": "a cute cartoon cat wearing an astronaut helmet, floating in space with stars",
     "criteria": "A cat wearing an astronaut helmet in a space/starry setting; coherent, not distorted."},
    {"id": "bar_chart",
     "prompt": "a clean infographic bar chart with four blue bars increasing in height, white background, no text",
     "criteria": "Four blue bars increasing left-to-right on a white background; reads as a bar chart."},
]

FLUX_DIMS = {768, 832, 896, 960, 1024, 1088, 1152, 1216, 1280, 1344}


def render_svg_to_png(svg_text: str, out_path: Path) -> bool:
    """Render SVG markup to PNG. Uses macOS QuickLook if available, else tries
    cairosvg. Returns False (rather than crashing) where neither is available —
    so SVG scoring is a best-effort nicety on Windows, not a hard dependency."""
    svg = _extract_svg(svg_text)
    if not svg:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 1) macOS QuickLook (no install needed).
    if shutil.which("qlmanage"):
        with tempfile.TemporaryDirectory() as td:
            svg_file = Path(td) / "in.svg"
            svg_file.write_text(svg)
            subprocess.run(["qlmanage", "-t", "-s", "512", "-o", td, str(svg_file)],
                           capture_output=True)
            thumb = Path(td) / "in.svg.png"
            if thumb.exists():
                out_path.write_bytes(thumb.read_bytes())
                return True
    # 2) cairosvg fallback (pip install cairosvg; needs libcairo).
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out_path),
                         output_width=512, output_height=512)
        return True
    except Exception:
        return False


def _extract_svg(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"<svg.*?</svg>", text, re.DOTALL | re.IGNORECASE)
    return m.group(0) if m else None


_VISION_RUBRIC = (
    "You are grading an IMAGE a model produced for a prompt. Judge only whether the "
    "image matches the request; ignore art style. Score 0-10: 9-10 clearly depicts it; "
    "6-8 recognizable with flaws; 3-5 partially; 1-2 wrong; 0 blank/unrelated. "
    'Return only JSON: {"score": <int>, "reason": "<=20 words"}.'
)


def vision_score(
    client: NemotronClient, image_path: Path, prompt: str, criteria: str, vlm: str = DEFAULT_VLM
) -> dict:
    """Have a vision model look at the rendered image and score it."""
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"{_VISION_RUBRIC}\n\nREQUESTED: {prompt}\nCRITERIA: {criteria}"},
            {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
        ],
    }
    r = client.chat(vlm, [msg], max_tokens=300, temperature=0.0, stream=False)
    parsed = _extract_json(r.text) or {}
    score = parsed.get("score")
    try:
        score = max(0, min(10, int(score)))
    except (TypeError, ValueError):
        score = 0
    return {"score": score, "reason": str(parsed.get("reason", ""))[:160], "ok": r.ok}


def run_graphics(
    image_models: list[str],
    svg_run_dir: Path | None = None,
    vlm: str = DEFAULT_VLM,
    steps: int = 25,
) -> Path:
    """Generate images from image-gen models, render any collected SVGs, and
    vision-score everything. Writes results/graphics/<stamp>/ + a leaderboard."""
    client = NemotronClient()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = config.RESULTS_DIR / "graphics" / f"run-{stamp}"
    (out / "images").mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    # 1) Image-generation models.
    for model in image_models:
        for task in IMAGE_PROMPTS:
            st = 4 if "schnell" in model else steps
            res = client.generate_image(model, task["prompt"], steps=st)
            row = {"kind": "raster", "model": model, "task": task["id"],
                   "latency": round(res.latency, 1), "ok": res.ok,
                   "resolution": f"{res.width}x{res.height}" if res.ok else None,
                   "score": None, "reason": res.error}
            if res.ok and res.image:
                p = out / "images" / f"{model.replace('/', '__')}__{task['id']}.png"
                p.write_bytes(res.image)
                sc = vision_score(client, p, task["prompt"], task["criteria"], vlm)
                row.update(score=sc["score"], reason=sc["reason"], image=str(p.relative_to(config.RESULTS_DIR)))
            rows.append(row)
            print(f"  raster {model:38} {task['id']:14} ok={res.ok} "
                  f"score={row['score']} {res.latency:.1f}s")

    # 2) SVG from chat models (rendered, then vision-scored on the paper-airplane prompt).
    if svg_run_dir:
        crit = "A recognizable paper airplane drawn as clean vector shapes."
        for tf in sorted(svg_run_dir.glob("*/tasks/creative_svg.json")):
            t = json.loads(tf.read_text())
            model = tf.parts[-3].replace("__", "/")
            png = out / "images" / f"svg__{model.replace('/', '__')}.png"
            if render_svg_to_png(t.get("output", ""), png):
                sc = vision_score(client, png, "a stylized paper airplane", crit, vlm)
                rows.append({"kind": "vector(svg)", "model": model, "task": "paper_airplane",
                             "latency": None, "ok": True, "resolution": None,
                             "score": sc["score"], "reason": sc["reason"],
                             "image": str(png.relative_to(config.RESULTS_DIR))})
                print(f"  svg    {model:38} score={sc['score']} :: {sc['reason'][:50]}")

    (out / "graphics.json").write_text(json.dumps(rows, indent=2))
    _write_graphics_leaderboard(rows, vlm)
    print(f"\nGraphics run → {out}")
    return out


def _write_graphics_leaderboard(rows: list[dict], vlm: str) -> None:
    raster = [r for r in rows if r["kind"] == "raster"]
    vector = [r for r in rows if r["kind"].startswith("vector")]
    md = "# Nemotron Bridge — Graphics Production\n\n"
    md += (
        f"Images **rendered and scored by a vision model** (`{vlm}`) against the prompt — "
        "not blind text grading. Score 0–10.\n\n"
    )
    if raster:
        md += "## Raster (text-to-image)\n\n| Model | Prompt | Score | Latency | Resolution |\n|---|---|---|---|---|\n"
        for r in sorted(raster, key=lambda r: (-(r["score"] or -1), r["model"])):
            md += (f"| `{r['model']}` | {r['task']} | {r['score'] if r['score'] is not None else '—'} | "
                   f"{r['latency']}s | {r['resolution'] or '—'} |\n")
    if vector:
        md += "\n## Vector (chat-model SVG, rendered)\n\n| Model | Score (sighted) | Note |\n|---|---|---|\n"
        for r in sorted(vector, key=lambda r: -(r["score"] or -1)):
            md += f"| `{r['model']}` | {r['score']} | {r['reason'][:60]} |\n"
    md += (
        "\n_Compare the vector scores here to the text-judge's `creative` scores in the "
        "main leaderboard: the sighted judge is far less forgiving of SVGs that don't "
        "actually look like the subject._\n"
    )
    (config.RESULTS_DIR / "graphics_leaderboard.md").write_text(md)
    print(f"Graphics leaderboard → {config.RESULTS_DIR / 'graphics_leaderboard.md'}")
