---
name: consult-jev
description: Consult Jev, TypeSafe AI's "System One" model, when code needs a calibrated typed judgment (closed-set choice with probabilities, rubric score, P(yes/no)). Use whenever a pipeline will classify, rank, filter, route, match, de-duplicate, screen relevance or pick a branch on messy input; when regexes or heuristics stand in for an expert's quick call; when an LLM is asked for JSON that code parses; before claiming a task needs fine-tuning or a reasoning model; or when the user says "ask Jev", "consult Jev", "use TypeSafe", "typed judgment" or "System One".
---

# Consulting Jev for typed judgments

Jev does not generate text. It takes a `state` plus a map of typed questions and returns
structured answers with probabilities. ~120–220 ms, $0.042 per million input tokens,
output free — so cost is almost never the constraint, and neither is latency.

**Repo:** `~/dev/Dispatch/providers/jev`
**Every question and threshold:** `~/dev/Dispatch/providers/jev/consultjev/questions.py`
**What is measured:** `~/dev/Dispatch/providers/jev/docs/FINDINGS.md`
**Pinned docs (920 KB, all 111 pages):** `~/dev/Dispatch/providers/jev/docs/typesafe_snapshot/llms-full.txt`

TypeSafe's own plugin is installed and is authoritative for API mechanics. This skill
carries the judgment their docs cannot: what was measured here, and what to distrust.

## The three question types

| type | asks | returns |
|---|---|---|
| `noul` | is this statement true? | a probability 0–1, **no confidence** |
| `choice` | which of these options? | the pick, a probability per option, a confidence |
| `score` | where on this rubric? | a probability-weighted value, a legend, a confidence |

All three mix in one call. Every question is evaluated independently and in parallel
against the same state, so **asking twelve costs barely more latency than asking one.**
Batch generously; there is no context-rot penalty for adding questions.

A `noul` returns no confidence because TypeSafe derives confidence from a probability
distribution and a noul has none. `confidence is None` means "not reported for this type",
never "zero".

## 🔴 Never read one question's answer alone

**The single most important rule here, and it was measured, not reasoned.**

Asked whether a passage was relevant to a risk, where the passage was the risk statement's
own wording quoted back as if it were a NASA citation — a known, already-retired
fabrication — Jev answered:

| question | answer | confidence |
|---|---|---|
| how does this relate to the risk? | `imposes_control` (p=0.89) | **0.84** |
| how specifically does it address it? | 3.97 / 4 | **0.97** |
| **is it a governance provision at all?** | **0.16** | — |

The relevance question was **confidently wrong**. The guard question was decisively right.

So decompose, and write the guard so it **cannot see the thing that would bias it**. The
guard above works precisely because it never mentions the risk, so the risk's wording
cannot drag it toward a verdict the way it dragged the relevance question. A guard that
shares the biasing input is not a guard.

This is TypeSafe's own doctrine — atomic questions, composed in code — arrived at from the
failure direction.

## 🔴 Confidence must never rank or filter

Measured, same run: confidence was **0.84–0.97 on the wrong answers** and **0.23 on the
one case where uncertainty was the correct response**. It ran backwards.

Use confidence as a **gate** — below a threshold, a human confirms — which is what
TypeSafe designed it for. Never sort by it, never drop the bottom of a list by it, never
report it as a quality score. If all you want is the best option, take the highest
probability; a confidence threshold adds nothing there.

## Two things Jev provably cannot do

Both measured. Recorded so nobody tries to tune their way to them.

**It cannot detect a fabricated quote.** Invented prose scored median 0.685 on "is this a
provision" against real source text's 0.655 — indistinguishable, because invented prose is
invented to look real. Jev is shown the passage and never the source, so no question can
establish whether text was copied or made up. That is a string comparison and belongs in
code. `DETECTS_FABRICATION = False`.

**It cannot reconstruct a magnitude from a score.** TypeSafe's own limitation: score levels
are weakly calibrated numerically. A score may be thresholded. It may not be interpolated
between levels to recover a number, and it may not be treated as a measurement.

## What it does well, measured

**Telling normative text from commentary.** Risk-echoed and non-normative text separates
cleanly from requirement text: 95% caught at a 5% false-flag rate, n=260. The distributions
barely touch (echo p90 = 0.11 vs live p10 = 0.15).

**Honest uncertainty on genuinely borderline input.** On a real provision that bore on the
question only indirectly, it returned a spread distribution at confidence 0.23 rather than
picking confidently. That is the behaviour a confidence gate needs to exist.

## Jev's published limitations that bite in practice

From `docs/typesafe_snapshot`, TypeSafe's `jev-1.13` jaggedness page:

- **Literal reading.** It answers the question as written, not as intended. When an answer
  looks wrong and you catch yourself explaining what you *meant*, **that explanation is the
  missing half of the instruction.** Put boundary cases in the criteria.
- **Large state full of irrelevant detail degrades accuracy.** Filter in code first and
  send only the fields the question needs. Pass structured named fields, not one prose blob,
  so a question can refer to a field by name in backticks.
- **No arithmetic, no counting, no date comparison.** Extract components with a Choice over
  a closed set — including an explicit "not stated" option — then do the maths in code.
- **Adversarial or self-arguing content moves the answer.** State is data, not treated as
  hostile. Text that argues for its own classification can shift the verdict.
- **Structural invariants are not guaranteed.** The same question as a noul and as a yes/no
  choice can disagree. Never build a consistency check that assumes they agree.
- **Indirection costs accuracy.** A property of a property, or a double negative, reads
  worse than a direct question.

## How to call it

```python
from consultjev import ask
from consultjev.questions import BATTERY, MODEL, build_state

response = ask(build_state(risk, passage), BATTERY, model=MODEL)
if response["is_a_provision"].noul <= NOT_A_PROVISION:
    ...  # non-normative; do not treat as a citation
```

The key is read from `TYPESAFE_API_KEY`, falling back to a key file outside the repo (the path comes from the private overlay, see `dispatchlib/providers.py`). It is
never in the repo.

## Writing questions

1. **One question, one well-scoped thing** — the judgment a knowledgeable person makes in
   a few seconds. If it needs extended reasoning or weighs independent factors, decompose
   and combine in code, where a priority change is a coefficient edit under review rather
   than a reworded prompt.
2. **Every question and threshold in one file.** This is the human review surface, and it
   is the thing a reviewer must actually be able to find. `questions.py` holds all of them;
   nothing else in the package defines a question or compares against a constant.
3. **Align criteria with instructions.** A noul whose `true` maps to "no" performs worse.
   Treat the criteria as an extension of the instruction.
4. **Do not pre-set a threshold.** Measure the distribution, then choose an operating
   point, and record the sweep beside the constant. Every threshold in `questions.py`
   either cites its measurement or says plainly that it is unmeasured.

## When NOT to reach for Jev

- **You need prose.** It cannot write. To "draft" text, write a closed vocabulary of
  options yourself and let Jev pick which apply; your code assembles the sentence from a
  template. That is a feature — a closed vocabulary is auditable and cannot invent an
  option you did not sanction.
- **A string comparison, parser or regex answers it exactly.** Then it is not a judgment,
  and a model can only make it less reliable.
- **You have no ground truth and the answer will be acted on.** Jev is calibrated, not
  correct. Without labels you cannot tell a well-calibrated wrong answer from a right one,
  and its confidence will not tell you either.
