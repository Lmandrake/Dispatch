---
name: nemotron-delegate
description: Use when a well-scoped subtask could be offloaded from Claude to a FREE NVIDIA Nemotron/NIM model to conserve paid budget or run wider in parallel — e.g. bulk summarization/classification of many files, boilerplate or test generation, first-draft code, data extraction to JSON, translation, or any high-volume "muscle" work where a cheaper model is good enough. Treat a free model as a per-subtask optimization choice, not an all-or-nothing switch. Do NOT use for the reasoning that must stay coherent across the whole task, for final user-facing judgment, or when correctness is safety-critical and unverifiable.
---

# Nemotron delegate

Offload well-scoped subtasks to NVIDIA's **free** hosted models so the user can
run projects at more depth and breadth than paid tokens alone allow. You (Claude)
stay the orchestrator; free models are cheap muscle for parts of the work.

## The one rule that matters

**Be transparent and verify.** Tell the user when you route a subtask to a free
model ("Delegating the 40-file summarization to `nemotron-nano` — free tier"),
and always sanity-check what comes back before you build on it. Free models are
rate-limited (~40 requests/min) and vary in quality — see the leaderboard.

🔴 **Verify means check it against reality, not read it for plausibility.**
Measured 2026-08-26: `nemotron-3-nano-30b-a3b`, given tools and a real corpus,
returned a confident, well-formatted answer citing **three files that did not
exist** — on 1 run in 3, having made zero tool calls. The output looked correct.
Nothing in the prose signalled that it was invented. So: if a free model names a
file, a line number, an API or a fact, **confirm the referent exists** before you
act on it. Never give a free model unsupervised write or delete authority.

## How to call a model

`nemo` is on PATH after setup (works the same on macOS and Windows):

```bash
nemo call <model-id> "<prompt>" --json        # structured output
nemo call <model-id> "<prompt>"               # plain text
nemo graphics                                  # image generation (FLUX) + graphics eval
```

For batches, loop and respect the rate limit (the client throttles to ~40 rpm
automatically, so back-to-back calls are safe). Capture `--json` and parse `.text`.

List available models: `nemo models`

## Check it is reachable BEFORE you pick it

**A model you cannot reach is not a good model, and quality rank says nothing
about availability.** Free-tier capacity is per-model and flaps between success,
429 and 404 from one call to the next — sampling 12 calls on 2026-08-26 found
`kimi-k3` (rank 1 for quality) answering **1**, while `nemotron-3-super`
answered 24/24 in the same loop.

```bash
nemo profile                      # uptime / latency / error-mix per model
nemo profile --probe 5 --models <id>   # sample now if the ledger is thin
```

Every `nemo` call feeds that ledger, so it stays current from ordinary use.
Verdicts distinguish states that look identical from one sample:

| Verdict | Means | Do |
|---|---|---|
| `healthy` | ≥95% of recent calls succeeded | use it |
| `flaky` / `capacity-limited` | succeeds sometimes | retry, or pick another |
| `unreachable (rate-limited)` | alive but starved | not for bulk work |
| `gone (sustained 404)` | 3+ sustained 404s | pick another |
| `retired (410 end-of-life)` | stated EOL | never comes back |

⚠️ **One 404 is not death.** It is routinely a capacity flap. Never strike a
model off on a single failed call — re-probe.

## Which model to pick

Read the current ranking + routing guidance first — regenerated from real
measurements, more accurate than anything hardcoded here. Locate them portably
(no hardcoded paths — works wherever the repo lives, incl. Google Drive):

```bash
nemo where            # prints repo_root, leaderboard, wisdom, registry, api_key status
```

Then read the `leaderboard` and `wisdom` files it points to:
- `leaderboard.md` — ranked quality + speed per model
- `WISDOM.md` — task-type → recommended model routing table

Measured defaults (availability re-checked 2026-08-26 — trust `nemo profile`
and the leaderboard over this table):

| Subtask | Start with |
|---|---|
| **Default / fast bulk / most delegation** | `nvidia/nemotron-3-nano-30b-a3b` — 9.5/10 at ~178 tok/s, 100% reachable |
| Balanced quality + speed | `nvidia/nemotron-3-super-120b-a12b` — 100% reachable, best agentic result measured |
| Top quality (latency-tolerant) | `nvidia/nemotron-3-ultra-550b-a55b` — 100% reachable today |
| Reasoning / extraction / instruction | `openai/gpt-oss-20b` — 9.88/10, ~80 tok/s, 100% reachable |
| Vision (image → text) | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (10/10) or `meta/llama-3.2-11b-vision-instruct` (fast) |

**Re-measured 2026-10-18 (light check, n=7 easy checkable prompts/model; see `evaluation/2026-10-18/RESULTS.md`):**
ultra-550b 7/7 (median 5.9 s), step-5-preview 7/7 (2.9 s, new), super-120b 7/7 (9.5 s), glm-5.3 7/7 but ~53 s median
(new, very slow), deepseek-v4.1-flash 1/7 with 6 timeouts at 170 s (new, unusable now). Ceiling effect: this does not
separate models or show parity with Claude. **Now HTTP 410 Gone: `kimi-k3`, `gpt-oss-120b`, `deepseek-v4-flash-0731`;
404 on chat: `kimi-k2.6`, `nemotron-4-340b`, `llama-3.1-nemotron-ultra-253b`, `mistral-large-2`.** Best default
for quality today: `nvidia/nemotron-3-ultra-550b-a55b`; for speed `step-5-preview` or `nemotron-3-super-120b-a12b`.
The kimi-k3 lines below are void.

**Retired — do not route here (confirmed 2026-08-26):**
- `deepseek-ai/deepseek-v4-flash-0731` — **gone**, 404 on 24/24 calls. Was the
  category leader for reasoning/extraction/instruction/summarization/creative;
  those recommendations are void wherever they still appear.
- `nvidia/nvidia-nemotron-nano-9b-v2` — **410**, stated EOL 2026-08-26T09:00:00Z.
- `mistralai/codestral-22b-instruct-v0.1` — 404.
- `nvidia/nemotron-nano-12b-v2-vl`, `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`,
  `nvidia/llama-3.3-nemotron-super-49b-v1.5` — **410**, all retired in the same
  batch at 2026-08-26T09:00Z. NVIDIA retires models in waves; re-check with
  `nemo profile` rather than trusting any list, including this one.
- `moonshotai/kimi-k3` — alive but ~8% reachable; one-off quality work only, never bulk.
- `poolside/laguna-xs-2.1` — top code score but ~33% reachable (500s). Retry-tolerant work only.

Avoid for bounded/interactive work: `llama-3.3-nemotron-super-49b` (slow,
truncates), `llama-3.1-nemotron-ultra-253b` (404).

## Give reasoning models token headroom, or they return nothing

Several free models emit hidden reasoning before the answer. If `max_tokens`
runs out mid-thought you get **an empty response, not a short one** — success
status, no content. Measured: an agent loop with `max_tokens=1500` produced two
consecutive silent turns from `gpt-oss-20b`; at 3000 the same task completed.

- Budget generously (2–3× what the answer needs), or pick a non-reasoning model.
- An empty-but-`ok` result means truncation, not refusal — retry with more room.
- At small budgets some models return their **chain-of-thought as the answer**
  ("The user asks… so we should output…"). Strip or re-prompt; don't hand that
  to the user.

## Tool-calling is a separate skill from chat quality

If the subtask needs the model to **drive tools** rather than answer once, chat
rank does not predict it — measured with `nemo agentic`:

- `nvidia/nemotron-3-super-120b-a12b` is **rank 14 on chat (7.5/10)** and gave
  the best agentic result: found every planted item, including one that required
  connecting two files. Prefer it for tool loops.
- `openai/gpt-oss-20b` scored **9.58, 0.0 and 6.3 on three identical runs** —
  the 0.0 was a clean 12-turn loop that simply never called the report tool.
- `poolside/laguna-xs-2.1` wrote the right answer in prose, then called `grep`
  again instead of submitting it.
- `moonshotai/kimi-k3` rejects requests carrying `tools=` — fine via `nemo call`,
  unusable as an agent backend.

**Termination is the least reliable behaviour.** Assume a tool-driving delegation
may end with no answer; always bound the turns and handle the empty case.

## When NOT to delegate

- The subtask needs context only you hold and can't be cleanly packaged.
- The output feeds a decision you can't cheaply verify.
- Latency matters and the candidate model is a heavy reasoner (some spend
  minutes "thinking" — the leaderboard flags slow/verbose ones).
- It's a handful of tokens — the round-trip and rate limit aren't worth it.
- The output would name files, paths or APIs you cannot cheaply confirm exist —
  free models confabulate specific-looking references (see the rule above).

## Good delegation patterns (with copy-paste recipes)

- **Fan-out summarization** — summarize many files, then you synthesize:
  ```bash
  for f in docs/*.md; do
    echo "== $f =="
    nemo call nvidia/nemotron-3-nano-30b-a3b "Summarize in 3 bullets:\n$(cat "$f")"
  done
  ```
- **Structured extraction** — free model emits JSON, you validate the schema:
  ```bash
  nemo call openai/gpt-oss-20b "Extract to JSON {name,email,role}: $TEXT" --json
  ```
- **Draft-then-refine** — free model writes a first draft; you edit for correctness
  (great for boilerplate, tests, docstrings, commit messages).
- **Parallel exploration** — ask 2–3 free models the same question and compare
  approaches cheaply before committing to one.
- **Bulk audit with mechanical verification** — the pattern that makes free-model
  analysis safe. Ask for candidates anchored to a **verbatim quote**, then check
  the quote actually occurs in the source before you read any of it:

  ```python
  # one call per file beats one long tool loop — see below
  items = json.loads(model_output)          # [{"quote":..., "why":...}, ...]
  for it in items:
      it["verified"] = it["quote"] in source_text   # <- discards fabrications
  real = [i for i in items if i["verified"]]
  ```
  Measured 2026-08-26 on this repo's docs: 74 candidates returned, **32 (43%)
  quoted text that did not exist**. This one line removed all 32 with no
  judgment required. Then verify the survivors' substance yourself — of the 42
  real anchors, only 1 was genuinely actionable (but it was worth the run: it
  found four end-of-lifed models sitting in live integration configs).

### Fan-out one call per item, don't build a tool loop

For analysing N files, make **N single-shot calls** rather than one multi-turn
agentic run. Measured today: tool loops repeatedly failed to *terminate* — models
investigated correctly for 12 turns and never submitted, or submitted an empty
list while their own reasoning was mid-sentence listing findings. Single-shot
per file is bounded, parallel-friendly, retryable, and each result is
independently verifiable.

⚠️ **Chunk anything over ~5k characters**, and treat an empty response as
truncation, not as "nothing found" — see the reasoning-headroom section above.

## Bulk vision / OCR offload

You (Claude) are already multimodal, so only offload images when there are **many**
of them and the paid cost matters. Route to a free VLM:

```bash
nemo call meta/llama-3.2-11b-vision-instruct "Describe this screenshot / read the text"   # + image
```

(For a single image you need to reason about, just look at it yourself.) Best free
VLMs: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` and `meta/llama-3.2-11b-vision-instruct`
(fast). See the vision leaderboard via `nemo where`.

## Generating images

That's a different skill — **`nemotron-image`** (uses `nemo image` / FLUX). Use it
when the user wants actual pixels, not text.
