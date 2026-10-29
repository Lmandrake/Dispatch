---
name: nemotron-image
description: Use when the user asks to generate, create, draw, make, or render an IMAGE, picture, logo, icon, mockup, concept art, illustration, texture, sprite, banner, or visual — anything that needs actual pixels. Claude Code has no native image generation; this produces real raster images for FREE via NVIDIA's hosted FLUX model. Trigger on "generate an image of…", "make a logo/icon/mockup", "draw me a…", "create a picture of…", "I need a visual for…". Do NOT use for diagrams best done as code (mermaid/SVG/matplotlib) unless the user specifically wants a photographic/painterly raster, or for editing an existing photo unless FLUX-kontext editing is requested.
---

# Nemotron image generation

Claude Code can't natively make images — but NVIDIA hosts **FLUX.1-dev** free
(~5s, 1024², genuinely good quality). Use this to fulfill image requests instead
of declining.

## Generate an image

```bash
nemo image "<detailed prompt>" --open
```

That generates a 1024×1024 PNG, saves it under `results/graphics/generated/`, and
opens it. Useful flags:

- `--out path/to/file.png` — choose the output location (e.g. into the user's project)
- `--size 1024` — one of 768,832,896,960,1024,1088,1152,1216,1280,1344
- `--steps 30` — higher = sharper/slower (20–40 is a good range); low steps or odd
  seeds can come out soft
- `--seed N` — change for a different variation; keep fixed to reproduce
- `--model` — defaults to `black-forest-labs/flux.1-dev` (the reliable free one)

## Prompting tips (FLUX)

- Be concrete about **subject, style, composition, colors, background**:
  e.g. `"a flat vector logo of a fox, minimal, orange on white, centered"`.
- FLUX doesn't reliably honor exact counts ("exactly 4 bars") or render clean
  text — for charts/labels/UI, prefer code (matplotlib/SVG). For photographic,
  painterly, or stylized art, FLUX shines.
- If the result is soft/blurry, bump `--steps` to 35–40 and/or try another `--seed`.

## Be transparent + verify

Tell the user you're generating it on NVIDIA's free FLUX (rate-limited ~40/min),
then **look at the result** (it's saved to disk — read/open it) and regenerate
with a refined prompt/seed if it doesn't match. Don't claim success without
checking the actual image.

## What's available (re-measured 2026-10-18)

- `black-forest-labs/flux.2-klein-4b` -- **newest, fastest**: 1-2 s at 1024^2, steps 1..4 only,
  dims multiples of 16 in 512..1568 with total pixels <= 1,062,400. Use `--model black-forest-labs/flux.2-klein-4b`.
  Returns JPEG. Legible short text (n=1, one glitch). Pass no `mode`/`cfg_scale`.
- `black-forest-labs/flux.1-dev` -- still works, ~5 s at 30 steps, steps >= 5.
- `flux.1-kontext-dev` needs an `image` field (editing). `flux.1-schnell` timed out at 40-90 s today.
- 404 today: flux.2-dev/pro/max/flex, SD3.x/SDXL, qwen-image, hunyuan-image, sana. Nothing better than
  FLUX-class is on the free tier. Details/curl shape: `evaluation/2026-10-18/IMAGE_MODELS.md`.

(Older note, partly superseded:)

Only the FLUX family is free-callable for images (`flux.1-dev` is the workhorse;
`flux.1-schnell` is faster but unreliable; Stable Diffusion / Imagen / Playground
are not available on the free tier). `nemo where` shows your setup.
