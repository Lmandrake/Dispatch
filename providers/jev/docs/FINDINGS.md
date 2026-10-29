# Findings

Measured results. Each entry says what was run, on how many cases, and what it does not
establish. A number with no denominator is not a finding.

---

## 2026-09-28 — First probe: does the battery discriminate?

**What ran.** The four-question battery in `consultjev/questions.py`, against
CoverageMap risk 22 ("Authority and Interface Containment"), on three passages drawn
from the live evidence ledger. `jev-1.13.0`, 120–220 ms per call, ~860 input tokens.

**n = 3.** This is a probe, not a characterization. It establishes that the battery
discriminates on hand-picked cases; it establishes nothing about a rate.

| case | relation | conf | is_a_provision | echoes_risk | specificity |
|---|---|---|---|---|---|
| NPR 2810.1F p.25, least privilege (real, strong) | `imposes_control` 0.99 | 0.98 | **0.96** | 0.11 | 3.30 / 4 (conf 0.42) |
| MIL-STD-882E p.18, hazard identification (real, indirect) | `mentions_context` 0.43 | **0.23** | 0.93 | 0.07 | 1.80 / 4 (conf 0.46) |
| risk text echoed back (**already-retired misfire**) | `imposes_control` 0.89 | **0.84** | **0.16** | 0.60 | 3.97 / 4 (conf 0.97) |

### The relevance question is fooled; the guard question is not

On the misfire, `relation` and `specificity` were both **confidently wrong** — 0.84 and
0.97 confidence on answers that are plainly incorrect, because the passage is the risk's
own wording rather than any NASA provision. `is_a_provision` returned 0.16.

This is the reason the battery has guard questions at all. `is_a_provision` deliberately
does not mention the risk, so the risk's wording cannot drag it toward a verdict the way
it dragged `relation`.

**Do not read `relation` alone.** Enforced by comment in `questions.py`; not yet enforced
by code, because no consumer exists yet.

### Confidence ran the wrong way

Confidence was highest (0.84–0.97) on the two wrong answers and lowest (0.23) on the one
case where genuine uncertainty was the correct response — the indirect MIL-STD passage,
where the distribution was honestly spread across three options.

This independently reproduces CoverageMap's standing rule that candidates must never be
ranked or filtered by model confidence. It arrived there from a different model's
behaviour; Jev behaves the same way on the same failure class.

### Calibrated uncertainty on the genuinely borderline case

The MIL-STD-882E hazard-identification passage is a real provision that bears on risk 22
only indirectly. Jev returned `mentions_context` at 0.43 with `imposes_control` 0.29 and
`offers_guidance` 0.27 — confidence 0.23. That spread is the right answer to a borderline
question, and it is what a confidence gate is for.

### Cost

~860 input tokens per candidate. The full live ledger of 6,980 links is roughly 6M input
tokens, about **$0.25** at $0.042/M, output free. Against the 100+ SME hours the
candidate set currently implies, cost is not a constraint on anything here.

---

## 2026-09-28 — Misfire benchmark, n=260

Artifact: `studies/misfire_benchmark_2026-09-28/result.json`. Reproduce with
`tools/benchmark_misfire.py --per-class 80 --seed 20260928`. `jev-1.13.0`, 260 calls, 0
errors.

Labels come from CoverageMap's retirement records, which are derived from **quote absence
in the source window** — a mechanism Jev is never shown. It sees only the passage text.

### `is_a_provision` by class

| class | n | median | p10 | p90 |
|---|---|---|---|---|
| `ECHOED_THE_RISK_TEXT` | 80 | **0.10** | 0.03 | **0.11** |
| `INVENTED_PROSE` | 80 | 0.685 | 0.13 | 0.92 |
| `QUOTE_NOT_PRESENT_IN_SOURCE` | 20 | 0.67 | 0.17 | 0.94 |
| live, quote present in source | 80 | 0.655 | 0.15 | 0.91 |

### Two results, one positive and one negative

**Risk-echo detection works, decisively.** The echo class has p90 = 0.11 while live text
has p10 = 0.15 — the distributions barely touch. Operating points:

| threshold | echo caught | live text flagged |
|---|---|---|
| `<= 0.12` | 95.0% | 5.0% |
| `<= 0.15` | 96.3% | 10.0% |
| `<= 0.20` | 98.8% | 16.3% |

**Fabrication detection does not work, and cannot.** Invented prose scored median 0.685
against live text's 0.655 — indistinguishable. This is not a shortcoming to tune away:
Jev is shown the passage and never the source, so no question asked of it can establish
whether the passage was copied or invented. CoverageMap's existing string comparison does
that exactly and this battery must never be described as backing it up.
`DETECTS_FABRICATION = False` records this in the code.

### A label of mine was wrong, and Jev caught it

The first run reported live text at median 0.27 and read as "Jev fails to recognise real
provisions". It was not. `LIVE_VERIFIED` in CoverageMap means *the quote is present in its
source*, which is a different property from *the quote is a governance provision*. The
sampled live text included a self-assessment question (*"Are you documenting your
development process and code well?"*), a form template (*"Condition: A single phrase,
sentence, or paragraph..."*), and descriptive handbook prose. Scoring those low is
correct.

So `is_a_provision` is measuring **normativity**. The class name in the benchmark was
changed to `LIVE_QUOTE_PRESENT_IN_SOURCE` so it cannot mislead the next reader the way it
misled this one.

### `echoes_the_risk` is measurably redundant

Flagged as the weakest question when it was written, then measured. OR-ing
`echoes_the_risk >= 0.50` into the `is_a_provision <= 0.15` rule moves echo detection from
96.3% to 97.5% with the false-flag rate unchanged at 10%. It has near-perfect specificity
(live p90 = 0.09) and poor sensitivity (echo p10 = 0.11, p90 = 0.96). Retained because it
rides free in the same call and its disagreement with `is_a_provision` is diagnostic, but
nothing gates on it.

---

## Thresholds and their basis

| constant | value | basis |
|---|---|---|
| `NOT_A_PROVISION` | 0.12 | **measured**, n=260 sweep above; 0.12 rather than 0.15 because the marginal echo caught costs twice the false flags |
| `ECHOES_THE_RISK` | 0.50 | measured redundant; not load-bearing |
| `AUTO_ACCEPT_CONFIDENCE` | 0.80 | **unmeasured** — TypeSafe's cookbook default, chosen to start high. No relevance ground truth exists to calibrate it against. |
| `DETECTS_FABRICATION` | False | measured, n=160 across two fabrication classes |

`AUTO_ACCEPT_CONFIDENCE` is the one constant still resting on nothing but a borrowed
default. It gates relevance verdicts, and relevance is the thing with no ground truth, so
it cannot be calibrated until an SME-labelled sample exists.

---

## 2026-09-28 — Spend guard, and the incident that shaped it

Total spend across all work on this date: **$0.0112** for 284 calls. $25 buys roughly
633,000 calls at this request size; the full 6,980-link ledger is $0.28. Cost is not a
constraint on anything here — but a *runaway* is, because an account can have a spending limit.

**What went wrong.** A test meant to prove the budget guard fires instead started a real
6,424-call run. Three separate defects lined up:

1. **The cap was too loose to catch the case being tested.** `--per-class 6000` clamps to
   the pool sizes, giving 6,424 calls at $0.25 — under the $0.50 default, so the guard
   correctly did not fire and the run proceeded. The test premise was wrong, not the guard.
   Default is now **$0.05**, so any substantial run is a deliberate act.
2. **`URLError` was unhandled.** A transient DNS blip escaped a worker and killed the run.
   The client retried `HTTPError` 429/529 but not network-layer failures, which are the
   more common transient. Now retried, and raised as `JevError` when exhausted.
3. **A crash discarded every answer already paid for.** Results were collected with
   `list(pool.map(...))`, so a failure partway through returned nothing. Now accumulated as
   they arrive and written to `.partial.json` on any exception, including a keyboard
   interrupt. This was the defect that actually wasted money.

**The guard could not be tested without spending money**, which is why it was tested
badly. `--dry-run` now samples, prints the estimate, and exits before any call — verified
to exit 0 while writing no artifact. The refusal path is verified to exit 2.

**Exact spend from the aborted run is unknown.** It crashed early, so it was small, but no
artifact survived to count from and the console balance is the only authority. Not
estimated here, because a number invented to close the loop would be worse than the gap.

---

## Jev's own published limitations that bear on this use

From <https://docs.typesafe.ai/model-jaggedness/jev-1.13>, reviewed 2026-09-17. The ones
that apply here:

- **Literal reading.** Jev answers the question as written, not as intended. Scoping
  words and negations are read at face value. When an answer looks wrong and the
  explanation of what you *meant* is missing from the instructions, that explanation is
  the bug.
- **Large state full of irrelevant detail.** Accuracy falls as the state grows with
  content the decision does not need. This is why `build_state` passes the risk as five
  named fields rather than a prose blob, and why `Mitigating Document(s)` is excluded.
- **Score is not numerically calibrated.** Do not interpolate between levels to recover a
  magnitude. A score may be thresholded; it may not be treated as a measurement. This is
  why `specificity` is kept for diagnostics and excluded from any ranking.
- **Adversarial content moves the answer.** State is treated as data, not as hostile. A
  passage that argues for its own classification can shift the verdict — which is
  precisely what the risk-text-echo misfire is, accidentally.
- **Structural invariants are not guaranteed.** The same question asked as a noul and as a
  yes/no choice can disagree. Do not build a consistency check that assumes they agree.

---

## Open, and honest about it

- **Relevance accuracy is UNMEASURED and currently unmeasurable.** Human labels exist for
  7 (risk, document) pairs. A reference set written by this build would grade it against
  its own author.
- **`n=3`.** Nothing here is a rate. The misfire benchmark is the next thing to run,
  because the 389 retired misfires are real labels produced independently of this work.
- **Risk 14** ("False Impression of Objectivity from Human-Like Interaction") found zero
  new candidates across two lexical passes and one mechanism pass in CoverageMap. Asking
  Jev about risk 14 is the highest-information single experiment available, because three
  unrelated methods have already returned nothing.
