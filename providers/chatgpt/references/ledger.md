# The effectiveness ledger

`providers/chatgpt/ledger/consults.jsonl` (git-ignored, or in the overlay), append-only, one JSON object per line. Central rather
than per-repo, deliberately: the question it answers — *is consulting worth its cost, and which
triggers earn their keep* — can only be answered across projects.

## Why it is shaped this way

The first version of this ledger recorded one row per consultation and one verdict per row. A GPT
review of this skill named the problem precisely: **the instrument reported success under conditions
where its own denominator and outcome classification were under its own control** — the exact pathology
the skill exists to catch elsewhere. Three consequences, each now a row type or a field.

**Only positive predictions were logged.** After tightening a trigger you could not distinguish "the
trigger got better" from "the trigger stopped seeing candidates". That is the denominator failure this
project has recorded three times in other guises.

**One verdict per consultation flatters a noisy reviewer.** A reply with one real defect, two minor
observations and six false alarms scored `found_real_defect`. Twenty of those look superb.

**Novelty was decided retrospectively.** Reading a reply and concluding "yes, I was sort of worried
about that" destroys the measurement. Hence the pre-consult belief snapshot.

## Row types

```jsonc
// 1. THE DENOMINATOR — every time a trigger is evaluated, including declines
{"type": "TRIGGER_OPPORTUNITY", "at": "...", "project": "ExampleProject",
 "repo_id": "a1b2c3d4e5f60718", "trigger": "measurement_machinery",
 "consulted": false, "suppression_reason": "formatting only",
 "trigger_rule_version": "2026-09-26.b", "skill_version": "0.2.0"}

// 2. THE CONSULT — written by the tool, success or failure
{"consult_id": "20260926T221431-ExampleProject-code_review", "started": "...",
 "project": "ExampleProject", "repo_id": "a1b2c3d4e5f60718",
 "kind": "code_review", "trigger": "measurement_machinery",
 "cold": false, "parent_consult_id": null,
 "belief_snapshot": "known: ...; hypothesis: ...; unsure: ...",
 "prompt_chars": 7284, "payload_hash": "9f2c...", "sent": true,
 "reply_chars": 21848, "reviewer_model": "gpt-5", "thread_url": "...",
 "wait_seconds": 96, "error": null,
 "skill_version": "0.2.0", "trigger_rule_version": "2026-09-26.b",
 "prompt_template_version": "2026-09-26.a"}

// 3. THE FINDINGS — one row per finding, added after acting on the advice
{"type": "FINDING", "consult_id": "...", "finding_id": "...#ledger-no-denominator",
 "novel_before_consult": "yes", "correctness": "confirmed",
 "verification_method": "test", "severity": "critical",
 "disposition": "applied", "rejection_reason": "",
 "applied": "abc1234", "fix_commit": "abc1234", "changed_plan": "no",
 "verified_by": "test", "duplicate_of": null, "note": "...", "recorded": "..."}

// 4. THE OUTCOME — one per DELIVERED consult; closes it (counts default to its FINDING rows)
{"type": "OUTCOME", "consult_id": "...", "findings_total": 6, "findings_confirmed": 5,
 "false_positives": 1, "applied": 5, "escaped_later": 0, "downstream_tokens": null,
 "no_findings": false, "outcome_note": "...", "recorded": "..."}

// 5. AN ESCAPE — append-only, a bug found later that this review should have caught
{"type": "ESCAPE", "consult_id": "...", "note": "...", "recorded": "..."}
```

`kind` ∈ `code_review`, `design_review`, `stuck_bug`, `impossibility_check`,
`universal_result_check`, `user_requested`, `other`.

`trigger` ∈ `measurement_machinery`, `risky_implementation`, `decision_bearing_design`,
`debug_stall`, `impossibility_claim`, `universal_result`, `user_asked`, `other`.

Kind and trigger stay separate because the same kind of question arrives for different reasons, and it
is the **trigger** whose value is being measured. A `code_review` the user asked for says nothing about
whether the proactive code-review trigger earns its place.

## Finding fields added 2026-10-16

`changed_action` was ambiguous (it meant "changed the plan", so 164 applied fixes said `no`). Old rows
are left as written; the reader maps them: `applied` is derived from `disposition`, `changed_plan`
from `changed_action`, `verified_by` from `verification_method`. New rows carry:

- `applied`: fix commit hash, `yes` (landed, no hash) or `none`; `fix_commit` the hash.
- `changed_plan`: yes/no, the old meaning only. `--changed-action` survives as a deprecated alias.
- `verified_by`: `requester` (the asking session read source), `independent_agent`, `test`, `human`.
  Default derives from `--verification`; pass it explicitly when an independent agent checked.

## Outcomes: finishing a consult

A delivered consult is not finished until it has an OUTCOME row. Errored or unsent attempts (the row
has `error`, or no reply) are already complete and are never nagged.

```bash
consult.py --record-outcome <id>                   # counts derived from its FINDING rows
consult.py --record-outcome <id> --no-findings     # nothing actionable: a valid outcome
consult.py --record-outcome <id> --downstream-tokens 7400000 --outcome-note "..."
consult.py --record-escape <id> --note "bug X, found later, review should have caught it"
consult.py --import-findings fixlog.jsonl          # or .csv; all-or-nothing
consult.py --pending-outcomes [--older-than-hours 24]
consult.py --stats                                 # per kind and trigger
```

`--import-findings` takes one finding per line (JSONL) or CSV with a header. Required: `consult_id`.
Optional columns use the `--record-finding` long names: `finding_id, novel, correctness, verification,
severity, disposition, rejection_reason, applied, fix_commit, verified_by, changed_plan,
duplicate_of, note`. Use it to bring findings out of a fix log into the ledger.

Every new consult prints up to five delivered consults older than 24h lacking an outcome, with the
command to close each. It nags and never blocks. Consults with trigger `pilot` are excluded from
nags and `--stats`. `--stats` counts errored attempts separately from delivered ones.

## The four outcome axes, and why they are not one label

| axis | values |
|---|---|
| `correctness` | confirmed · disconfirmed · unresolved |
| `novel_before_consult` | yes · no |
| `severity` | informational · minor · major · critical |
| `disposition` | applied · deferred · rejected (+ `rejection_reason`) |

Collapsing these cannot distinguish **good advice rejected because the trade-off is wrong for the
project** from **bad advice that happened to be harmless**. Both were `advice_rejected` in the first
design, which made the label useless.

**`correctness: confirmed` requires a `verification_method` other than `none`** — the tool refuses
otherwise. A second model asserting a defect is not evidence of one; that is the standing authority
rule, and the ledger is where it matters most, because this is the record that decides whether to keep
trusting the channel.

`duplicate_of` exists so an iterative "please re-review the fix" session cannot count one bug several
times.

## Reading it back

```bash
consult.py --ledger          # opportunities, consults, findings; yield per trigger version
consult.py --ledger --full   # every row
```

The summary reports **verified-novel yield over opportunities**, not over consultations, and prints
`n/a (no opportunities logged)` when the denominator is missing rather than a flattering ratio over
whatever happened to be recorded. It also counts consultations with no findings — those measure nothing
and are the ledger's own failure mode. If most rows are unclosed, recording needs to be *easier*, not
enforced harder.

## The actuator

A ledger nothing acts on is decoration. Precommitted: **every 25 opportunities per trigger version**,
compute verified-novel yield, major/critical yield, false-finding rate, duplicate rate and burden, then
decide — keep, narrow, or demote from auto-send to draft-only — and **record the decision**.

No universal "below 10% means disable" bar, per the user's standing rule that tolerances are set after
measurement rather than before. A 3% yield of catastrophic defects may be excellent. What is required is
an explicit decision point.

**A trigger-definition change starts a new cohort.** That is what `trigger_rule_version` is for, and why
every row carries `skill_version` and `prompt_template_version` too: otherwise in six months you will
pool measurements from materially different systems and call them one population.

## Evolving the skill on this evidence

The triggers are initial parameters. Change them the way this project changes anything — cite the rows.
"Narrowing `risky_implementation` to changes touching a high-risk class, because 18 of 22 opportunities
escalated and produced 1 verified-novel finding" is defensible. "Feels like too many consults" is not,
and a skill edited on impression drifts back within a month.
