# Model ladder on an enterprise gateway: when does Haiku 5.5 or Sonnet 5.5 earn the work? (2026-10-20)

Question (owner): dispatch to a smaller model only when it buys latency or cost, decided per
task. Is "it's not whether the task is simple, it's whether a wrong answer can be checked"
true, or hearsay? Does Claude already do this natively?

Sources in this directory: `anthropic-guidance.md` (first-party docs, system cards),
`literature.md` (papers), `github-survey.md` (public GitHub practice). Data: `data/`.
Harness: `tools/ladder/` (raw caches under agent storage, `<agent-storage>/<project>/ladder/`).
Prices are the published list prices used for all cost figures here. Total spend for the experiments: about $45.

## Answer

The hypothesis holds on our measurements, with two refinements.

1. **Uncheckable task (SimpleQA, factual recall, n=400, one sample each):**

   | arm | correct | WRONG | abstain | $/item | median s |
   |---|---|---|---|---|---|
   | Haiku 5.5 (medium) | 0.180 | 0.458 | 0.362 | 0.00029 | 2.9 |
   | Haiku 5.5 high | 0.182 | 0.443 | 0.375 | 0.00035 | 3.2 |
   | Sonnet 5.5 (high) | 0.458 | 0.420 | 0.122 | 0.00520 | 3.9 |
   | Opus 5.5 (medium) | 0.710 | 0.265 | 0.025 | 0.00728 | 3.6 |
   | Opus 5.5 low | 0.705 | 0.280 | 0.015 | 0.00581 | 3.0 |

   Haiku is wrong more often than it is right. Paired bootstrap, Haiku minus Opus: correct
   -0.58 to -0.48, wrong +0.13 to +0.26 (95%). Effort does not rescue it. Its own stated
   confidence is informative (>=80%: 28 of 36 correct) but covers 9% of items, so a
   confidence-gated cascade must escalate ~91% of items to reach 0.695 correct, at 98% of
   Opus-alone cost and twice the latency. **No cheap check exists for this kind of work, and
   the small model is not cheaper once you pay to make it right.** The cheapest real saving
   here is Opus at low effort (-20% cost, no measurable loss).

2. **Checkable task (LiveCodeBench v6, 175 problems after the training cutoffs; check = the
   problem's public example tests; truth = hidden tests, run in a network-less container):**

   | strategy | correct | $/problem | mean s |
   |---|---|---|---|
   | Opus x1 | 0.823 | 0.044 | 19 |
   | Sonnet x1 | 0.811 | 0.025 | 17 |
   | Haiku x1, unchecked | 0.766 | 0.002 | 17 |
   | Haiku up to 5 until public tests pass, else Opus | **0.846** | **0.014** | 46 |
   | Haiku up to 5, else Sonnet | 0.829 | 0.0085 | 44 |

   With the check, Haiku matches Opus at a third of the cost (difference vs Opus -0.03 to
   +0.07, 95%). Without it, Haiku loses about 6 points, all on medium and hard problems
   (easy: 1.00 for every model). **Refinement 1: difficulty still matters when there is no
   check;** checkability is what lets you stop caring about it.

3. **Refinement 2: the check is not free of error.** Public tests passed code that failed the
   hidden tests 3.4% of the time for Opus, 5.1% Sonnet, 7.7% Haiku. A weaker check admits
   more of the weaker model's errors, so "checkable" means a check whose false-accept rate
   you know.

4. **Latency is not a reason to drop a tier on reasoning work.** Per call, Haiku was no faster
   than Opus on code (median 9 s vs 10 s; it writes more tokens) and only ~0.7 s faster on
   one-line answers. The check-and-retry loop that makes it safe more than doubles wall-clock.
   Haiku buys cost, not speed, except on trivially short calls.

## Does Claude already do this?

Partly, and the part it does is the folklore. A headless Claude Code session on Opus 5.5
(clean config, no CLAUDE.md, 5 task kinds x 3 reps, `data/native-routing-*`) set the subagent
`model` itself on every spawn: 26 haiku, 16 sonnet, 3 opus. It sent **factual recall to Haiku
9 of 9 times** (the case above where Haiku is 18% correct) and file searches and extraction to
Haiku, code to Sonnet, review to Opus. It is routing by perceived simplicity. It got away
with it on the three recall questions only because Opus re-checked the answers from its own
memory, which is the checker paying for the work. Documented Claude Code behaviour adds
nothing automatic beyond background tasks and `opusplan` (see `anthropic-guidance.md`).
So a routing rule is not redundant; its job is to replace "simple" with "checkable".

Anthropic's own guidance already says this in one line ("High-volume work with outputs you
can check: try Claude Haiku 5.5 first"), and its Haiku 5.5 system card says Haiku
"hallucinated more than other recent models". Haiku is best kept to mechanically checked tasks.

## Proposed rule (not yet wired into `bin/delegate`)

- **Haiku** only when a mechanical check of the output runs before anyone relies on it
  (tests, schema, compiler, exact-match lookup, a grep that can be re-run), and the
  dispatcher escalates on a failed check. Searches and inventories whose result the caller
  re-verifies qualify; recall, summaries, extraction a human will trust, and judgments do not.
- **Sonnet** for well-specified work with no mechanical check where a few points matter less
  than cost (code: -1 point vs Opus at 58% of cost).
- **Opus** for anything uncheckable where being wrong is costly; prefer **Opus at low effort**
  over a lower tier when the goal is only cost.

## Limits

One sample per arm per item; temperature fixed by the gateway. SimpleQA is adversarially
selected against GPT-4-class models, so absolute rates are low for everyone; the ranking is
what transfers. The grader is Sonnet 5.5 low on OpenAI's verbatim template, calibrated 80/80
on positive, negative, empty and "I don't know" cases. Cascades are computed offline from
independent samples. Native routing is n=15 sessions, one prompt per kind, and the prompts
asked for subagents explicitly.
