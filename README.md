# Dispatch

Dispatch is a command-line router for people who run many AI coding agents and need to decide, per
task, which model and which agent harness should do the work. It replaces a leaderboard or a hunch
with a small set of rules backed by experiments run in this repo, and it carries the provider code,
benchmarks and Claude Code skills those rules came from.

It answers four questions:

- **Which Claude tier** a subagent gets (`delegate tier`): Sonnet is the floor, a failed mechanical
  check escalates to Opus, Opus when a miss is costly. Haiku is banned (owner, 2026-10-31).
- **Which harness** drives it (`delegate harness`): Claude Code, Pi or OMP, per task class.
- **Which second opinion** a review gets (`delegate second-opinion`): a cross-provider GPT pass, a
  second Opus, or a Sonnet critic.
- **Which destination** can take the job on this machine right now (`delegate where`, `route`):
  local, free, enterprise and external models, each behind its own readiness probe.

## What is different here

- **Rules that are re-checked.** Every figure the router prints is computed at call time from
  committed result files, and the tests fail if a direction a rule rests on reverses.
- **Three-valued probes.** A destination is ready, not ready or unknown, and unknown never blocks a
  spawn. Nothing mirrors another component's state; the router asks each destination's own probe.
- **Rule 0.** If a task is deterministic (parsing, formatting), `delegate tier parse` answers
  "no model: write Python".
- **One tree, five former projects.** ChatGPT consulting, Jev (TypeSafe) typed judgments, the
  Nemotron/NIM bridge, the Pi/OMP harness study and the local oMLX evaluation were separate
  repositories. They now live under `providers/` and `harnesses/` so the router runs from a single
  clone.

## Providers

| destination | what it is for | where | private part |
|---|---|---|---|
| Claude tiers (Sonnet, Opus) | the default workers; tier chosen by checkability | an enterprise gateway, model ids read from the environment | none in code |
| oMLX local | on-machine models; nothing leaves the laptop | `providers/omlx/` (code, fixtures, measured throughput) | none |
| Nemotron / NIM | NVIDIA's free hosted models, public data only | `providers/nemotron/` | key file outside the repo |
| Jev (TypeSafe) | calibrated typed judgments: choice, score, P(yes) | `providers/jev/` | key-file pointer, account note |
| GPT | an independent second opinion and open-web research | `providers/chatgpt/` | account pointers, consult ledger |
| Enterprise model service | an optional remote endpoint, reached through a plugin | a separate private plugin, registered by the overlay | the whole plugin |
| Harnesses | Claude Code, Pi, OMP: what drives the model | `harnesses/` (benchmarks and results) | none |

Private material (account pointers, ledgers with thread URLs, internal hostnames) lives in an overlay
outside this repo, found by `dispatchlib/providers.py`: `$DISPATCH_OVERLAY` (one directory per provider),
else a private directory you point it at. With no overlay every
provider reports "not configured" or "not cloned" and the router still answers.

## Measured results

1. **A cheap model earns work when a wrong answer will be caught, not when the task looks simple.**
   Code with a check (LiveCodeBench v6, 175 problems): Haiku up to 3 tries until the public tests pass,
   else Opus, scored 0.84 against Opus alone at 0.82, at 29% of Opus's cost. Factual recall with no
   check (SimpleQA, n=400): Haiku was wrong 46% of the time, and a confidence-gated cascade had to
   escalate 91% of items, at 98% of Opus's cost. The owner banned Haiku everywhere on 2026-10-31
   for its error rate, so that saving is no longer on offer: Sonnet is the floor.
   Source: `docs/research/2026-10-20-model-ladder/FINDINGS.md`, data in `.../data/`.
2. **A second independent review pass pays. A cross-provider pass ties on recall and wins on false
   alarms; its main value is independence.** On 42 real escaped bugs (14 snapshots, 7 repos, 3 runs
   per shape, scoped packets), one Opus review recalled 0.42. A second blind Opus reached 0.51, a
   blind GPT 0.53, a Sonnet critic of the Opus review 0.53. GPT minus a second Opus: +0.03 recall
   (90% CI -0.03 to +0.08), a tie. Judged false alarms added per run: about 0.9 for the second Opus,
   about 0.1 for GPT, which also costs no Claude tokens. GPT's real value is that it is a different
   provider, account and training lineage, which matters for assurance. Giving the reviewer the
   whole repo instead of the change cut one-Opus recall from 0.42 to 0.15 (a partial run, stopped at
   the token cap after 68 of 135 calls). The router encodes this:
   `second-opinion --independence` routes to GPT; otherwise a second Opus or a Sonnet critic.
   Summary table: `docs/MEASURED_RESULTS.md`.
3. **On the same model, the harness does not change task success, but it changes cost a lot.**
   Short edits (10 tasks, n=3, Sonnet 5.5): Claude Code 30/30, Pi 30/30, OMP 29/30. Pi took 30% less
   wall time and sent about 8x less context per task (12k against 93k tokens). On five harder tasks
   all three tie within 90% intervals (Pi 23/30, Claude Code 20/30, OMP 20/30, pooled over two runs),
   and Pi is still fastest (median 78 s against 122 s).
   Source: `harnesses/docs/CAPABILITY-2026-10-23.md`, `CAPABILITY-2026-10-24-hard.md`,
   `CAPABILITY-2026-10-25-full-hard.md`; summary table: `docs/MEASURED_RESULTS.md`.
4. **Local CPU per agent: Pi about 0.4 CPU-s per headless task, Claude Code as configured about 3.9.**
   Claude Code with `--bare` costs about the same as Pi; most of the gap is configuration (hooks,
   plugins, MCP), not the harness. OMP is the heaviest at the same payload. Small n (3 headless
   reps), one busy laptop on battery.
   Source: `harnesses/docs/FINDINGS.md`; summary table: `docs/MEASURED_RESULTS.md`.
5. **Claude Code was the only harness with no crash or stall** across 120 capability runs (Pi 1,
   OMP 3), and the only one whose hooks and permission rules run. So `delegate harness` keeps Claude
   Code whenever guards are needed and prints what the measurements alone would pick.
   Source: `harnesses/docs/FEATURES.md`; counts in `docs/MEASURED_RESULTS.md`.

## Quick start (no private overlay needed)

Python 3.9+ and nothing else; the router is stdlib only.

    git clone https://github.com/Lmandrake/Dispatch.git && cd Dispatch
    python3 bin/delegate where --no-probe              # what this machine declares, no network
    python3 bin/delegate tier code --check "pytest -q" # Sonnet, then Opus, with evidence
    python3 bin/delegate tier judgment                 # Opus: no mechanical check exists
    python3 bin/delegate tier parse                    # no model: deterministic Python (rule 0)
    python3 bin/delegate harness hard-coding           # Claude Code / Pi / OMP, with the table
    python3 bin/delegate harness metered --no-guards   # what the measurements alone pick
    python3 bin/delegate second-opinion --independence # GPT if reachable, else says it cannot

`delegate where` (without `--no-probe`) runs each destination's own probe; with no keys and no
overlay they report "not configured" or "not cloned" rather than failing.

## Layout

- `bin/delegate` the CLI and the single source of the ladder; `dispatchlib/` the router
  (`tiers`, `harness`, `second_opinion`, `capability`, `delegate`, `ledger`, `prior`, `providers`).
- `routing/destinations.json` the destination registry.
- `providers/chatgpt/` (was ChatGPTConsult) second-opinion consulting through a logged-in browser.
  `providers/jev/` (was ConsultJev) the Jev client, question battery and benchmark.
  `providers/nemotron/` (was Nemotron_Bridge) the NVIDIA NIM accessor, registry and assessment
  harness. `providers/omlx/` (was DispatchOpenCode) local-model routing code and measured
  throughput. Each keeps its own probe (`docs/PROBE_CONTRACT.md`), README and tests.
- `harnesses/` (was NewHarness) the Pi and OMP launchers, method and findings under
  `harnesses/docs/`. The raw run results are not published; `docs/MEASURED_RESULTS.md` holds the
  summary tables.
- `skills/` the Claude Code skills for each route.
- `benchmarks/capability-suite/` the frozen coding task suite the harness results come from.
  Reference solutions are deliberately withheld from this public copy, so only the tasks and
  the frozen-manifest check run here.
- `docs/research/2026-10-20-model-ladder/` the tier study behind result 1.

## Status and limits

Sample sizes are small throughout and are stated beside each result. Some destinations (GPT,
Jev, enterprise endpoints) need your own accounts and keys, which this repo does not contain. The
harness results come from one machine and one model family, and are a snapshot, not a ranking.

## Tests

    python3 -m pytest -q                                 # the router
    (cd providers/jev && python3 -m pytest -q tests)
    (cd providers/chatgpt && python3 -m pytest -q tests)
    (cd providers/nemotron && python3 -m pytest -q tests)
    (cd providers/omlx && python3 -m pytest -q evals/harness/tests)

The router suite runs from a bare clone with nothing beside it; the oMLX destination's
evaluation code and evidence are in `providers/omlx/`.

## Credit

Please credit me if you find this work useful.
