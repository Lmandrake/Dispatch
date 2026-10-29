# The delegation router, reviewed cold by a second model

Step 0 of the plan was a ChatGPT
consult on the design before building. Done 2026-10-01, `--cold` (a fresh conversation,
no inherited repo context, so the reviewer could not ratify our vocabulary), reviewer
`gpt-6-pro`.

**Standing rule, applied here: a second model's answer is guidance, never authority.** It
may not override a standing ruling and may not be cited as proof anything is correct. What
follows is what the review found, and what each finding actually changed — including the
three places it was wrong or where a standing ruling stands against it.

## The one finding that changed the design

**"Empirical overrides prior" is not an executable decision rule.** The plan precommits
that at 20 dispositions for a (destination, task-kind) cell, the empirical rate overrides
the prior. The reviewer's T3: the prior holds benchmark percentiles, throughput and cost;
a used-as-is fraction is none of those, and nothing in the design says how a 90%
used-as-is rate is compared against an intelligence index of 70. Without that mapping,
"overrides" would silently treat a benchmark percentile as an expected acceptance
probability.

**Resolution: the threshold is implemented, the override is not.** `ACTUATION` stays
precommitted at 20 and every row carries its version — that property was the point and
abandoning it would let the number be chosen later to fit the data. What is *not* built
is any code that replaces a prior with an empirical rate. `ledger.cells()` computes the
rates and labels the cell `provisional` or `empirical`; `bin/delegate` prints prior and
observed **side by side** and ranks on the prior. Wiring the override needs a defined
mapping between two unlike quantities, which nobody has written.

Two further reasons the reviewer gave, both accepted as limitations rather than fixed:

- **T1 — nineteen unequivocally bad experiences cannot act.** A minimum-sample rule
  blocks responding to directly observed operational failure. Mitigated by giving
  *operational* observations their own authority: a launch failure updates reachability
  immediately and does not wait for twenty of anything. Disposition-based reranking is
  what waits.
- **T2 — twenty records need not be twenty experiences.** One fan-out can produce twenty
  near-identical jobs. `batch_id` is recorded so siblings are countable, and
  `cells()` reports `n_batches` beside `n_dispositions`. Row count is not evidence
  breadth.

For the record, the reviewer's own arithmetic on what a threshold could buy under ideal
conditions: zero adverse dispositions in 20 jobs gives a one-sided 95% upper bound of
`1 - 0.05^(1/20)` ≈ **13.9%** on the adverse rate; getting that under 5% needs 59 jobs.
That is a statement about dispositions, not correctness, and it assumes complete
recording and independent jobs — neither of which holds here. It is recorded because it
bounds what the number can ever mean, not because it argues for a different number.

## What it corrected about the hook

**H1 — the hook enforces destination validity, not routing policy.** An agent that
ignores `delegate` and spawns a served, reachable model straight from a stale prose
instruction is *allowed*, with no DECISION row and no prediction. The plan called the
hook "makes it binding", which oversells it.

**Accepted and renamed.** The hook is an **availability-and-name guard**. Making routing
itself binding needs either a launcher that records and dispatches together, or a third
check for a missing routing receipt — and the reviewer's H2 shows a receipt cannot be a
"last decision" file, because two concurrent jobs would read each other's. Per-invocation
association is not available in the `Agent` tool schema today, so this is left undone and
stated, not approximated.

**H3 — `print(err, file=stderr); exit(0)` is not a loud failure path.** On exit 0,
Claude Code sends hook stderr to the debug log only; it reaches neither the agent nor the
transcript. So the plan's "fail open loudly" was, as written, fail open *silently* — a
router bug would make the guard inert with nothing reporting it. **Fixed**: the fail-open
path emits a structured `systemMessage` and appends to a local health record that
distinguishes three states which an exit code cannot:

```
evaluated: no routing denial
evaluated: routing denial
not evaluated: cache/schema/internal failure
```

"Process exited 0" is not "the guard checked the request."

**H4 — a healthy script that never runs.** Every unit test passes while the matcher is
wrong or the hook is unregistered, and no internal handler fires. Partly addressed: the
health record makes silence detectable from outside the guard. A full
spawns-versus-receipts reconciliation is not built.

## What it corrected about the ledger

- **A third event family.** `DECISION` (router intent + prediction) · `ATTEMPT`
  (execution adapter: what was actually tried, and what happened operationally) ·
  `DISPOSITION` (what the consumer did with the result). **Implemented.** The reason is
  L3, *launched is not completed* — which is the exact failure already measured here: a
  `model: fable` spawn returns a successful launch and then dies on HTTP 400. Two row
  types record the launch as the outcome.
- **L1 — two rows do not separate "prior wrong" from "box busy".** Both worlds produce
  `predicted 4s / measured 40s`. **Accepted as a limitation**: the design's claim that the
  split makes them distinguishable was too strong. `bin/delegate ledger` reports
  "duration exceeded prediction; cause unresolved" and does not diagnose.
- **D3 — a self-report is not an observed action.** An agent calling
  `record --disposition used-as-is` and then writing something different is the previous
  grader failure under a new field name. **Implemented**: `disposition_source` is
  `observed_operation | actor_report | human_report`, required, and `actor_report` is
  never counted as observed use.
- **D1 — "no edits" and "no review needed" are different properties**, and this bites
  hand-off-first ranking specifically, since DELEGATE means "you need not read it".
  **Implemented**: `review_status` is `none | performed | unknown`, separate from the
  disposition.
- **D5 — corrections manufacture sample size.** Ten outputs later re-marked `discarded`
  are ten observations, not twenty. **Implemented**: `supersedes` links the correction and
  `cells()` counts only the latest disposition per decision.
- **D6 — recording selects the answer.** 20 recorded of 100 returned permits a true rate
  anywhere from 20% to 100%. **Implemented**: `n_unknown` is carried beside every rate and
  no rate is ever printed without its coverage.
- **A2 — a cell survives replacement of its subject.** Swap an 8-bit build for a 4-bit one
  under the same served name and the favourable cell keeps applying. **Implemented**:
  `config_fingerprint` on every DECISION; evidence attaches to a route configuration, not
  a display name.
- **A6 — "no text in the ledger" fails through diagnostics.** An exception handler that
  serialises a hook payload leaks the input even though every normal row is clean.
  **Implemented**: the privacy tests now include malformed payloads and exception paths,
  not only successful rows.

## What it corrected about the cache

**C5 — the clock can move backward**, making a snapshot's age negative and therefore
fresh forever. **Fixed**, and it was live: the first draft computed
`time.time() - ts > ttl` with no lower bound.

**C1 — freshness is not sufficiency.** A five-second-old snapshot of account A's
catalogue says nothing about account B after a switch. **Fixed**: `hook_verdict` refuses
to use a snapshot whose subscription does not match the live environment, and treats the
facts as unknown.

**C2 — refreshing one source must not rejuvenate another.** A successful gateway refresh
with a failed local refresh would carry "local down" forward under a new timestamp.
**Fixed**: each observation carries its own timestamp and status.

**The governing rule, adopted verbatim in spirit:** *expired evidence becomes unknown — it
neither proves availability nor remains grounds for denial.* That is the answer to the
plan's open question about which direction staleness should fail in, and it differs by
decision: stale never blocks, and only a *fresh, correctly scoped* catalogue may.

**C3 — the corporate probe proves the wrong proposition.** A reachable network is not an
authorised endpoint, and the probe host may be down while the real destination is routed
differently. **Accepted**: `consults()` keeps network reach, credentials and destination
readiness as separate fields and says so in the `why` string.

## Exploration: where it corrected our hypothesis

We asked whether the ledger can only ever confirm the prior. **Partly wrong**: a *selected*
destination can disconfirm its prior — repeated rewrites say the favourite is not serving
the workflow. What the ledger cannot establish is how an *untried* destination would have
done; E1 makes the point that a world where the challenger is better and a world where it
fails every job produce identical logs.

The reviewer's cheap mechanism — a small budgeted random share (e.g. 0.05) among
challengers *already eligible* for that job, assigned once per logical task, with the
eligible set and the selection probability recorded — is **not implemented in v1** and is
recorded here as the designed next step. E2 is the trap to avoid when it is built:
deterministic "every twentieth request" exploration correlates with workflow position, so
a fan-out of nineteen small extractions plus one large synthesis sends the synthesis to
the challenger every time. E3: shadow execution yields telemetry, not a disposition, and
having a model compare the two outputs reintroduces the grader.

**The boundary it insisted on keeping visible:** a route excluded from all real work cannot
be rehabilitated by this ledger at all. It needs changed external evidence or an explicit
user-authorised trial.

## Speed, and the `--want` flag

**S1/S2 — keep deadline and hand-off requirements separate.** A six-second budget makes a
4-second cleared model the only candidate even though a 28-second cleared model scores
higher; with no budget the ranking reverses. And when the only cleared route is 28s and the
caller wants unattended hand-off in 6s, the answer is **"no route meets both
requirements"** — never a silently relaxed review requirement. The user's ordering is
preserved exactly: *among feasible routes*, cleared-for-hand-off first, then score.

**S4 — a throughput measurement is not a duration prediction.** `routing/throughput.json`
is one short warm prompt; a real task has a long input, a possible cold load, and queueing.
So `delegate` distinguishes a time *budget* from a *forecast of completion*, and does not
promise the second.

**S3 — availability is not capacity.** Five spawns each reading "local is idle" from a
cached snapshot each predict four seconds; oMLX executes serially and the last finishes
around twenty. A snapshot cannot reserve capacity. Not solved in v1; recorded as a real
defect of any cached-availability design, and the fix belongs in an execution adapter with
an atomic reservation.

**`--size N` was undefined** — input tokens, expected output tokens, document count and
total context are not interchangeable. **Fixed by definition**: `--size` is *input tokens*,
stated in the help text.

## Where the review was wrong, or where a ruling stands

1. **It recommended removing the 20-disposition precommitment from the first build.** The
   precommitment is kept. Its purpose is that the rule cannot be chosen later to fit the
   data, which is a failure this repo has already paid for three times in a different form.
   What was removed is the *override*, which is the part T3 actually showed to be
   undefined — the threshold itself costs nothing and buys the property.
2. **It treated the disposition signal as possibly unobtainable and therefore suspect.**
   Accepted as a finding about instrumentation, but it is not a reason to delay: an honest
   ledger showing that most workflows produce no learning signal is itself the answer to
   "is this worth building", and it is cheaper to learn from a built ledger than from more
   design.
3. **Its citations are leads, not sources.** The reply carries search-reference markers for
   the binomial bound, the contextual-bandit framing, and several Claude Code
   documentation claims. The `systemMessage` and exit-code claims were checked against the
   harness's own behaviour before being acted on. The bandit and binomial references were
   **not** retrieved and nothing here rests on them beyond the arithmetic, which is
   reproducible in one line.

## The three tests it said the first build must pass

Adopted as the acceptance criteria for v1:

1. **An invalid destination never appears as a completed dispatch.**
2. **A spawn that bypasses routing is visible as unrouted.**
3. **An absent disposition remains unknown** — never a 100% rate over whatever got recorded.
