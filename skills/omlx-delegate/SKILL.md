---
name: omlx-delegate
description: Hand a piece of stateless language work to a free local model on this machine instead of doing it yourself — classifying, extracting, triaging grep output, reducing log noise, tightening or de-hyping prose, drafting a slide outline or release notes. Use when a task matches one of the measured jobs below and the input is ordinary working material. It routes from measured evidence, refuses the jobs local models are known to fail, and tells you when a verdict is not actually earned. Do NOT use for action-item extraction or anything where attribution matters, for agentic work that touches files, or when no measured job fits — a miss is the correct answer, not a nearest match.
---

# Delegating to a local model

🔴 **THIS IS THE PROCEDURE, NOT THE DECISION.** `delegate-router` is the front door —
it decides whether local is where the work belongs at all, weighing it against the
sanctioned gateway and the consults, under a deadline if you have one. Come here once
the route says local. One thing it will tell you that this skill cannot: **local is not
free, and on a short job it is not even cheap** — measured at 400 output tokens, the
local 27B costs more than Sonnet 5 on the gateway and takes far longer. Local's
advantage is that nothing leaves the machine.

```bash
~/dev/Dispatch/bin/delegate route E3 --expect-output 400
```

This skill lives in Dispatch; the oMLX destination it drives (`bin/route`, `bin/roster`,
`evals/`, `references/`) is in `providers/omlx/` (`$DISPATCH_OMLX` overrides it), and
every `./bin/...` below runs from there.

There is a published-evidence routing table behind that repo. This skill is how a
session reads it, picks a model, and dispatches — and, just as importantly, how it
declines.

**The whole point is a free run on hardware already paid for. The cost is that you
have to know which jobs survive it.** Most of the eight measured jobs do; some need
checking; action-item attribution is a do-not-delegate for every model, local or
frontier. **Do not carry a count in your head or quote one from this file** — the
verdicts move whenever a fixture is hardened or a sweep lands. `./bin/route show
--all` is the current answer and takes a second to run.

## Before anything else: is there a measured job for this?

The table covers **eight** jobs. It does not cover the other 48 activities in the
decomposition, and **a miss is the correct answer** — the table does not claim
coverage it does not have. If the task in front of you is not one of these, do the
work yourself and say that no measured job fit.

| code | the job | fixture |
|---|---|---|
| `A2` | **Grep triage.** From `grep -n` output, list the distinct source files with a real TODO — no line numbers, no duplicates, excluding `vendor/` and `node_modules/`, excluding prose-only mentions. | `evals/suites/mechanical/A2-grep-triage.json` |
| `A3` | **Log signature reduction.** From an app log, list the distinct ERROR-level failure signatures, deduplicated, without letting WARN/INFO lines that merely contain the word "error" leak in. | `evals/suites/mechanical/A3-log-signatures.json` |
| `B4` | **Garbled-term repair.** From a transcript, list the proper nouns / acronyms / orgs the transcription mangled, with a best-guess correction, marking genuinely unclear ones uncertain. | `evals/suites/ingestion/B4-garbled-terms.json` |
| `B5` | **Action items with attribution.** Who agreed to do what. | `evals/suites/ingestion/B5-action-items.json` |
| `E3` | **Prose tightening** without meaning change — and **without dropping a hedge** (`may`, `possible`, `approximately`, `we believe`). | `evals/suites/prose/E3-prose-tightening.json` |
| `E4` | **De-hyping.** Strip promotional adjectives, keep every concrete claim and number. | `evals/suites/prose/E4-neutralize-hype.json` |
| `F1` | **Deck outline** from a brief: N bullets, only facts present in the source. | `evals/suites/artifact/F1-deck-outline.json` |
| `F2` | **Release notes** from a commit log: Features and Fixes, only `feat:`/`fix:` commits. | `evals/suites/artifact/F2-release-notes.json` |

**Read the fixture before you classify.** Those one-liners are summaries; the fixture's
`prompt` field is the exact instruction the measurement was taken against, and the
numbers only describe work shaped like that.

## Procedure

**1. Ask what the table says, and read the tier, not the percentage.**

```bash
cd "${DISPATCH_OMLX:-$HOME/dev/Dispatch/providers/omlx}" && ./bin/route show A2
```

Runs anywhere — it needs no server and calls no model. Three verdicts:

- **`DELEGATE`** — hand it over. A cheap glance at the result is still sensible; a
  careful review is not required.
- **`VERIFY`** — usable, but you are on the hook for checking the output. **Read the
  reason**, because two different problems land in this tier. "got it right on most
  runs, usable but check the result" is a model limitation. "a copy of the input
  scores the same on this job" is an *instrument* limitation: the test cannot tell
  doing the work from repeating the question, so its score is not evidence about the
  model at all.
- **`DO NOT`** — keep it. `B5` is here for every local model, and the reason is the one
  worth remembering: a model that fabricates an owner produces output that reads
  perfectly and is wrong about who owes you work.

**2. Check the table is not stale before you trust it.**

```bash
./bin/roster --check
```

A model in `missing` is never selected. If the table is stale or the roster hash has
drifted, prefer the conservative choice over a confidently stale ranking — and say
out loud that you did.

**3. Decide sensitivity, and be pessimistic about it.**

**If any part of the input derives from this machine's files, repositories, mail, or
the user's data, the task is sensitive. If you are unsure, it is sensitive.** For
sensitive input, only `local` egress is acceptable — which is what dispatch already
enforces: `run_job` refuses anything that does not classify as loopback-served
`omlx`, and it fails closed when the sanctioned-host config is missing or malformed.
This step is enforced by you, not by code. That is a deliberate accepted risk in the
design, so treat it as yours to get right.

**4. Dispatch.**

```bash
./bin/route run A2 --input /absolute/path/to/material.txt
./bin/route run E3 --prompt "…the text to tighten…"
```

**Hand over the material only, not an instruction.** The job's instruction comes from
its fixture and is appended for you, in the exact envelope the measurement used
(`material`, a `---` rule, then the fixture's prompt). This is what makes the table's
numbers applicable to your dispatch, so writing your own instruction defeats it —
`--raw` exists for that and is off-distribution from every number in the table.

`--input` wins over `--prompt`. Exit codes: **2** nothing to dispatch (or an empty
input file — it refuses rather than quietly answering a different question), **3**
refused (a `DO NOT`/`UNKNOWN` tier, or a non-local endpoint), **4** truncated twice so
no output, **5** no measured job for that code and therefore no instruction to
compose. Nothing is written to disk and no prompt or output text is stored anywhere.

`./bin/route run A3 --fixture-input` dispatches the job's own measured material — a
live end-to-end check that the server, the gate and the envelope all still work,
costing one free local call.

Add `--force` only to override a `DO NOT`, and only with a reason you would defend
out loud. It does not override the egress gate — nothing does.

**5. Report honestly.**

Say which model ran it and at which tier. On `VERIFY`, either do the check or say
plainly that it is unchecked. Never present a local model's output as your own
finding — the user cannot tell the difference afterwards, and the tier is exactly the
information they need to decide how hard to look.

## Things that are true and cost time to rediscover

- **Plain mode, not thinking mode.** Thinking was measured to not help local models
  and usually to hurt: the 27B-8bit fell from 80% to 17% on garbled names. `nothink`
  is the default for that reason, not for speed.

- 🔴 **Published benchmarks say the OPPOSITE about thinking, and they are not wrong
  — they measure different work.** Artificial Analysis rates `Qwen3.8 27B` markedly
  HIGHER at xhigh effort than non-reasoning, a large gain from the very setting the
  sweep above measured as catastrophic. Both hold: their index is dominated by
  hard-reasoning benchmarks (GPQA, HLE, SciCode, long-context) while every job in
  the table above is **mechanical fidelity** — repair this transcript, extract these
  owners, do not invent. Reasoning helps the first and actively hurts the second, so
  the sign of the effect flips with the shape of the task.

  **What that does and does not license.** It does NOT license turning thinking on
  for any job in the table — the measurement in the bullet above is on our actual
  work and wins there. It says the headroom is real but lives in a task shape we
  have never measured and currently refuse outright. A reasoning-shaped job added
  here must be swept on its own; neither result transfers.

  Two corollaries. **Effort is a bigger lever than model choice** — the coherence
  probe found the model effect indistinguishable from zero, while effort moves this
  one model by more than the entire spread between our local models. So "which
  local model" matters far less than "which mode, for which shape of task". And
  **do not go shopping for a better local model on the strength of an index**: many
  open-weight models outscore ours, but everything that both fits this machine's
  memory and beats `Qwen3.8 27B` at xhigh is a far larger mixture-of-experts whose
  4-bit haircut erases the gain. The fleet is not the bottleneck.

  Figures behind this: `providers/omlx/references/artificial-analysis-cost.json`
  (retrieved 2026-09-30) and `charts/06-intelligence-vs-cost.html`. Re-read them
  rather than trusting a number quoted here.
- **A truncated response is withheld, not returned.** Dispatch retries once at double
  the budget; if it hits the ceiling again you get no text, because a cut-off response
  is as likely to be the model reasoning as an answer.
- **The percentages are not all measured the same way.** A tier computed on the
  *atoms basis* has been checked for traps and structure, not just keywords. A cell
  still on the legacy basis cannot reach `DELEGATE` at all, and says so in its reason.
- **Per-job, not per-model.** There is no general "good local model" here — the
  coherence probe found the model effect indistinguishable from zero. The same model
  can be perfect on one job and fail nearly every run on another. Always ask per
  activity.

- 🔴 **oMLX SELF-DOCUMENTS at `/openapi.json`. Read it before touching the GUI.**
  Measured 2026-10-01: a 129 KB OpenAPI 3.1 spec covering ~90 paths, including the
  whole `/admin/api/*` surface the menubar app drives — per-model settings, model
  load/unload, HF download and search, benchmarks, server restart. An error message
  saying *"Enable X for this model"* names a **field on
  `PUT /admin/api/models/{model_id}/settings`**, not something only a human can click.

  The detour this replaces: `K2-Horizon-MoVA-36B-A4B-8bit` 409'd needing Trust Remote
  Code; `omlx serve --help` has no such flag, `settings.json` has no such key, the
  `app.omlx` defaults domain holds only window geometry, and the Models view is a
  **popover that closes when the app is activated**, so AX enumeration found zero
  windows. All of that was avoidable — the spec had `trust_remote_code` all along.

  Three specifics worth keeping:
  - **The admin API needs its own session.** `POST /admin/api/login` with
    `{"api_key": <the key from the oMLX settings file>, "remember": true}` and keep the
    cookie; the Bearer token alone gets `401 Admin authentication required`.
  - **Admin model ids are BARE.** `K2-Horizon-MoVA-36B-A4B-8bit`, not
    `mlx-community/K2-Horizon-MoVA-36B-A4B-8bit` — the prefixed form 404s, which reads
    like a missing endpoint rather than a wrong id. `/v1/*` wants the prefix.
  - **`POST /admin/api/reload` re-discovers models without restarting the server**,
    which is the cheap version of the restart below.

- **A new model needs a server restart, and `omlx restart` may not be the one to use.**
  `/v1/models` can list one fewer model than sits on disk. The
  running server can be an **unmanaged** `omlx-server` (for example started by
  the menubar app), in which case `omlx stop` reports success having stopped nothing and
  `omlx start` raises a **blocking GUI dialog** — *"Port 8000 is in use"* — that sits on
  the screen until something clicks OK. Check `lsof -nP -iTCP:8000 -sTCP:LISTEN`
  first, and prefer `POST /admin/api/reload`. If you do raise a dialog, dismiss it:
  `osascript -e 'tell application "System Events" to tell process "oMLX" to click button "OK" of window 1'`.

- **Downloading weights: do not filter `*.py` out.** A `snapshot_download` with
  `allow_patterns=["*.json","*.safetensors",...]` silently omits a custom architecture
  module (`k2_horizon.py`), and the model then fails to load for a reason that reads as
  a policy problem rather than a missing file. HuggingFace's own `hf-cli` and `hf-mem`
  skills exist (official `huggingface-skills` plugin) and are the better route.

## What this skill is not for

- **Agentic work** — anything that edits files, runs commands, or needs a working
  tree. That is `opencode-subagent`'s job (designed, not built) and it requires an
  isolated worktree; do not improvise it with this skill.
- **Anything unmeasured.** The jobs in the table are the extent of what has been
  earned. Stretching one of them to cover a task it does not describe throws away the
  only thing that made delegation safe.
