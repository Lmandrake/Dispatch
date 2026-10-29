# Assessment rubric

You are grading the output of a candidate model on one task. You will be given
the task prompt, the task's success **criteria**, and the model's **output**.

## Per-task scoring (0–10)

Score ONLY against the task's criteria. Ignore verbosity/style unless the
criteria mention it.

- **9–10** — Fully correct; meets every criterion; nothing a careful reviewer
  would fix.
- **7–8** — Correct in substance; a minor slip (one constraint loosened, small
  stylistic issue) but usable as-is.
- **5–6** — Partially correct; the core is right but a real error is present
  (wrong edge case, one criterion clearly missed).
- **3–4** — Mostly wrong; shows some understanding but the result is not usable.
- **1–2** — Wrong or off-task.
- **0** — Empty, refused, or unparseable/errored.

Return strict JSON: `{"score": <int 0-10>, "reason": "<= 25 words"}`.

## Nearest-Anthropic tier (aggregate, per model)

After all tasks are scored, map the model's overall profile to the nearest
Anthropic capability tier. This is a **rough qualitative anchor**, not a
benchmark claim — state confidence. Anchors (Claude 4.x family):

- **~Haiku tier** — Fast and competent on straightforward coding, extraction,
  and summarization. May stumble on multi-step logic puzzles, strict multi-
  constraint instructions, or subtle edge cases. Good for bulk/simple work.
- **~Sonnet tier** — Strong general-purpose coding and reasoning. Reliable
  structured output and instruction-following. Handles most everyday
  engineering subtasks correctly the first time. The workhorse default.
- **~Opus tier** — Top-end reasoning and coding. Handles subtle multi-step
  logic, tight simultaneous constraints, and nuanced tradeoffs reliably.
- **below-Haiku** — Frequent correctness failures even on simple tasks.

Consider: correctness rate across categories, whether it nails the *reasoning*
and *instruction* tasks (the tier discriminators), and reliability (JSON/format
adherence, refusals). Weight reasoning + coding highest.

Return strict JSON:
`{"tier": "<below-Haiku|~Haiku|~Sonnet|~Opus>", "confidence": "<low|medium|high>", "rationale": "<= 40 words"}`.
