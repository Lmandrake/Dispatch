> Folded into Dispatch as `providers/nemotron/` on 2026-10-25 (git subtree, history kept).
> Its two skills moved to `Dispatch/skills/nemotron-delegate` and `nemotron-image`.

# Nemotron Bridge

Make NVIDIA's **free** [build.nvidia.com](https://build.nvidia.com) models
(Nemotron + the whole free NIM catalog) trivial to drop into multi-model
workflows — so a free, rate-limited model becomes just an **optimization choice
for a portion of a task**, not an all-or-nothing switch.

Free models are limited by *rate* (~40 requests/min), not tokens. That's a
different optimization axis than paid Claude usage: offload the high-volume,
"good-enough" muscle work to free models and spend your paid budget where
judgment and coherence matter. Done well, you get more **depth and breadth** per
dollar.

## What's here

| Piece | What it does |
|---|---|
| **Accessor** (`nemotron_bridge/client.py`) | Thin wrapper over the OpenAI SDK pointed at NVIDIA NIM. Streaming, reasoning-token capture, ~40 rpm limiter, retries, vision helpers. |
| **Registry** (`registry.py`, `models.yaml`) | Self-seeds from the live `/v1/models` catalog and infers each model's modality. The catalog churns weekly, so it's reconciled, never hand-maintained. |
| **Assessment harness** (`assess.py`, `metrics.py`, `judge.py`, `report.py`) | Measures each model and produces re-runnable **scorecards** + a **leaderboard**: latency, velocity, max rate, quality, and a nearest-Anthropic tier. |
| **Skills + command** (`../../skills/nemotron-*`, `commands/`) | Claude Code plug-and-play: `nemotron-delegate` (offload subtasks), `nemotron-image` (generate images with FLUX), `/nemo-proxy` (run Claude Code itself on free models). |
| **Integration configs** (`configs/`) | Run Claude Code, OpenCode, Codex, or aider on NVIDIA's free models. |

## Claude Code capabilities this adds

Once installed (below), Claude Code can:
- **Offload subtasks to free models** — `nemotron-delegate` skill routes bulk
  summarization, extraction, drafting, and vision/OCR to the best free model.
- **Generate images** — `nemotron-image` skill turns "make a logo/mockup/picture"
  into a real PNG via FLUX (Claude Code can't do this natively). CLI: `nemo image "..." --open`.
- **Run on free models** — `/nemo-proxy` starts a LiteLLM proxy so a new Claude
  Code session (or just its subagents) runs on NVIDIA's free models. *Verified
  end-to-end: the Anthropic `/v1/messages` path translates to NVIDIA and returns 200.*

### Install the skills/command (two options — pick one, don't do both)

- **Bootstrap (default, above):** `scripts/setup.sh` / `setup.ps1` copies the
  skills into `~/.claude/skills/` and the command into `~/.claude/commands/`.
- **As a plugin:** this repo is also a Claude Code plugin + single-plugin
  marketplace. In Claude Code:
  ```
  /plugin marketplace add <local path to this directory>
  /plugin install nemotron-bridge@nemotron-bridge
  ```
  You still need the `nemo` CLI (run the bootstrap for the venv + key); the plugin
  only delivers the skills/command.

## Install on each machine (macOS and Windows)

Three things are **per-machine**: the Python venv (platform-specific), your `NVIDIA_API_KEY` (secret), and
the Claude Code skill registration. A one-time bootstrap handles all three.

**macOS / Linux:**
```bash
cd "/path/to/Nemotron"        # e.g. ~/Drive/dev/Nemotron
bash scripts/setup.sh
```
**Windows (PowerShell):**
```powershell
cd "C:\path\to\Nemotron"      # e.g. G:\My Drive\dev\Nemotron
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Each script installs [`uv`](https://docs.astral.sh/uv/) if needed, installs the
**`nemo`** CLI globally (`uv tool install --editable .` — tracks this repo, works
from any directory, on both OSes), copies the `nemotron-delegate` skill into
`~/.claude/skills/`, and checks for your key. Set the key once per machine:

- macOS/Linux: add `export NVIDIA_API_KEY=nvapi-...` to your shell profile
- Windows: `setx NVIDIA_API_KEY nvapi-...` (open a new terminal after)

Free key: build.nvidia.com/settings/api-keys. In Claude Code, run `/reload-skills`.

> **Sync note:** treat **GitHub as the source of truth** (push/pull); let Drive
> mirror for convenience. Editing on two machines at once can create Drive
> "conflicted copy" files (especially under `.git`). Re-run `setup` after pulling
> so the installed skill copy refreshes.

> **2026-10-18 refresh:** catalog and image models re-measured -- see `evaluation/2026-10-18/` (`RESULTS.md`, `IMAGE_MODELS.md`, `catalog_diff.md`). New fast image model `flux.2-klein-4b`; kimi-k3 / gpt-oss-120b now 410.

## Quickstart

```bash
nemo where                             # repo + artifact paths, key status (portable)
nemo models --refresh                  # seed/refresh the registry from the live catalog
nemo call nvidia/nemotron-3-nano-30b-a3b "Summarize the CAP theorem in 2 lines."
nemo all --preset flagship             # assess the headline models
nemo leaderboard                       # deduped master leaderboard across all runs
nemo graphics                          # image-gen (FLUX) + SVG, scored by a vision model
nemo agentic --preset agentic          # multi-turn tool-calling: can it drive an agent loop?
```

## The metrics

See [docs/metrics.md](docs/metrics.md) for exact definitions. Headline set:

- **Response latency** — time to first token (TTFT) + total wall time.
- **Response velocity** — decode tokens/sec (counts hidden reasoning tokens too).
- **Max rate** — empirically probed requests/min before rate limiting.
- **Multimodal input** — whether vision models accept and correctly read images.
- **Graphics production** — image-gen models (real images) and chat models
  (SVG/mermaid quality), the graphics that matter in a coding session.
- **Nearest comparable Anthropic model** — a rough qualitative tier
  (`~Haiku` / `~Sonnet` / `~Opus`) from a judged task battery.
- **Reliability** — success rate, format adherence, refusals, truncation.

## Using free models in your tools

See [docs/integrations.md](docs/integrations.md). Summary:

- **Claude Code / Cowork** speak Anthropic's `/v1/messages`; NVIDIA's cloud is
  OpenAI-only, so route Claude Code through a **LiteLLM** proxy
  (`configs/litellm.config.yaml`). **Cowork is a closed product and cannot use
  custom backends** — use an OSS agent framework instead.
- **OpenCode / Codex / aider** accept an OpenAI base URL directly — no proxy
  (`configs/`).
- **Inside Claude Code**, install the `nemotron-delegate` skill and let Claude
  offload subtasks to free models with your paid session as the orchestrator.

## Re-running as the catalog changes

Everything is re-runnable. `nemo models --refresh` picks up new models; `nemo all
--preset flagship` regenerates the leaderboard. The routing guidance in
[WISDOM.md](WISDOM.md) is derived from the latest run.
