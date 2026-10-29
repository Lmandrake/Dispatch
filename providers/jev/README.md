# Jev provider (was ConsultJev)

Folded into Dispatch as `providers/jev/` on 2026-10-25 by `git subtree`, history kept. The skill is
`Dispatch/skills/consult-jev/`. Tests: `cd providers/jev && python3 -m pytest -q tests`.


Consult **Jev**, TypeSafe AI's "System One" model, for typed and calibrated judgments —
and measure whether it is good enough to trust before wiring it into anything.

Jev does not generate text. It takes a `state` plus a map of typed questions and returns
structured answers: a choice with a probability per option, a score against a rubric you
define, or a "noul" — a probability that a yes/no statement is true. Answers come back in
roughly 120–220 ms, priced at $0.042 per million input tokens with output free.

## Status: evaluation, not production

This repo deliberately stops short of a pipeline. It holds the documentation, a client,
the question battery, and a benchmark — so the question "is Jev good enough for this job"
gets a measured answer rather than an argued one.

Its first evaluation subject is a governance-coverage project (referred to as the coverage project in these notes): can
Jev judge whether a cited agency provision is relevant to an AI risk statement?

## What is measurable, and what is not

This distinction is the most important thing in the repo.

| Capability | Ground truth available | Status |
|---|---|---|
| Detecting misfires (a passage that is not a real provision) | 389 retired misfires, labelled independently of this build | **measurable** |
| Judging relevance to a risk | 7 human-asserted (risk, document) pairs, total | **not yet measurable** |

Relevance has almost no human ground truth, and a reference set written by whoever built
the thing being tested measures agreement with its author, not correctness. So the
benchmark reports misfire detection honestly and reports `UNKNOWN` for relevance. It does
not produce a relevance number it cannot defend.

## The finding that shaped the design

Asked about a passage that was a risk statement's own wording quoted back as if it were a
NASA citation — a real, already-retired misfire — Jev answered:

| question | answer | confidence |
|---|---|---|
| how does this relate to the risk? | `imposes_control` (p=0.89) | 0.84 |
| how specifically does it address it? | 3.97 / 4 | 0.97 |
| **is it a governance provision at all?** | **0.16** | — |

The relevance question was **confidently wrong**. The guard question was decisively
right. Two consequences, both enforced in `consultjev/questions.py`:

1. **Never read the relation answer alone.** The guard questions are the reason the
   battery is safe to use, not decoration on it.
2. **Never rank by confidence.** Here confidence was 0.84–0.97 on the wrong answers and
   0.23 on the one honest, genuinely-uncertain case. Confidence went the wrong way.

## Layout

```
consultjev/client.py       stdlib-only client for POST /v1/systemone, retries 429 and 529
consultjev/questions.py    EVERY question and EVERY threshold, in one reviewable file
docs/typesafe_snapshot/    pinned copy of TypeSafe's docs, sha256-stamped
docs/FINDINGS.md           measured results and the traps behind each threshold
docs/CREDENTIALS.md        where the API key lives, and why not here
studies/                   benchmark runs and their artifacts
```

## Use

```python
from consultjev import ask
from consultjev.questions import BATTERY, MODEL, build_state

response = ask(build_state(risk, passage), BATTERY, model=MODEL)
print(response["is_a_provision"].noul, response["relation"].choice)
```

The API key is read from `TYPESAFE_API_KEY`, falling back to
`the consultjev env file`. It is never stored in this repo.

## The official TypeSafe skill

TypeSafe publishes its own Claude Code plugin, which is authoritative for API mechanics
and stays current:

```bash
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
```

This repo does not duplicate that. What it adds is the judgment their docs cannot carry:
which questions to ask for *this* problem, what the guards are for, and what was actually
measured.
