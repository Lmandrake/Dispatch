# Capability comparison: Claude Code, Pi, OMP on the same model (2026-10-23)

Question: beyond local CPU (`docs/FINDINGS.md`), what does each harness do better or worse when it actually codes? Feature-level comparison from source: `docs/FEATURES.md`.

## Design

- Suite: 10 tasks in `harnesses/bench/tasks/` (bug fix, CLI feature, multi-file rename, spec implementation, order-dependent test bug, one-function edit in a 2000-line file, override-chain search, noisy output, messy-log parser, O(n^2) fix). Graded by hidden pytest files copied in after the agent exits. Every task was checked to fail on the untouched repo and pass with a reference solution.
- Runner: `harnesses/bench/capability_bench.py`. The harness is the only thing that differs. Arms: **claude-stock** (Claude Code 2.1.292 with an empty config dir and CLAUDE.md loading off: default tools, no hooks, plugins, MCP or instructions), **pi** (1.4.0, default 4 tools), **omp** (18.12.6, default tools). Same gateway, model, `medium` thinking, prompt and bearer token. 3 reps, 6 runs at a time, harness order rotated per task and rep.
- Per-run data and transcripts are not published; the tables here are the record.

**Load-bearing runs: `cap-sonnet-final` and `cap-haiku-final`.** The earlier runs each had a defect in one arm, listed under "Defects found and fixed", and are kept only as evidence for those defects.

## Results (final runs, n=3 per task per arm)

| | claude-stock | pi | omp |
|---|---|---|---|
| **Sonnet 5.5**: passed | 30/30 | 30/30 | 29/30 |
| median wall per run, s | 11.2 | **8.2** | 11.8 |
| total wall, s | 416 | **295** | 434 |
| median input context per run (read + write + fresh), tokens | 93k | **12k** | 50k |
| median output tokens | 986 | 840 | 868 |
| median CPU, s / peak RSS, MB | 1.1 / 276 | **0.7 / 161** | 2.2 / 470 |
| **Haiku 5.5**: passed | **30/30** | 29/30 | 29/30 |
| median wall per run, s | 18.1 | **14.7** | 27.8 |
| median input context per run, tokens | 228k | **26k** | 108k |
| median turns / tool calls | 7 / 6 | **5 / 6** | 7 / 8.5 |
| median CPU, s / peak RSS, MB | 1.6 / 309 | **1.2 / 168** | 2.8 / 483 |

Per-task tables are in each run's `SUMMARY.md`.

## What this supports

- **Task success does not separate the harnesses on this suite.** All three solve essentially everything with Sonnet and with Haiku. Every failure in the final runs was operational (a crash or a stalled stream), not a wrong answer. The suite is at ceiling, so it cannot show a capability gap smaller than about 1 task in 10. Harder, longer tasks would be needed for that.
- **Pi is the fastest and leanest on the model side.** With Sonnet it took 30% less total wall time than Claude Code, and it sent about 8x less context per task (12k against 93k tokens). The gap is its small system prompt and 4-tool schema against Claude Code's 20 tools and 16 built-in skills. On a metered or rate-limited gateway this is the largest difference measured today, larger than the local CPU difference.
- **OMP matches Claude Code on Sonnet speed and is slowest on Haiku** (about 1.5x Claude's median). It uses more read/grep calls, and has 2x the CPU and 1.7x the memory of Claude Code.
- **Claude Code was the most reliable**: 60/60 completed with no crash or stall, in these and all earlier runs once its config leak was removed.

## Reliability, all runs today (operational failures, not wrong answers)

| harness | failure | count | cause |
|---|---|---|---|
| omp | exits after about 1 s with `SQLiteError: ... agent.db: table settings already exists` | 3 of 216 OMP runs | race when several OMP processes start at once on one agent dir (first-run schema creation). A per-run agent dir or a warm-up run would avoid it. |
| omp | headless `-p` hangs forever at `readPipedInput` if stdin is not redirected | every time | waits on an inherited stdin. Always pass `</dev/null`. |
| pi | node is SIGKILLed (rc 137) before it starts when the prompt is passed as an argument | every time for this one prompt (task 09) | **not Pi**: `node /tmp/x.js "<that prompt>"` is also killed, while python, echo and the native Claude binary are not. Likely the test Mac's endpoint protection matching node plus that text (inferred). Piping the prompt on stdin avoids it. |
| pi, omp | a stream stalls mid tool call and never finishes (killed at 900 s) | 1 each with Haiku | the same stall the pilot saw in Pi. Cause unknown (gateway or client). Neither harness has a stream idle timeout that caught it. Claude Code had none in its 216 runs today. |

## Defects found and fixed (why the earlier runs are not load-bearing)

1. **Pi sends custom-provider Claude 5 models fixed-budget thinking, not adaptive effort.** With a custom `anthropic-messages` provider, Pi uses `budget_tokens` (8192 at `medium`) unless `compat.forceAdaptiveThinking` is set. Claude Code and OMP use adaptive effort. Effect in `cap-haiku` and `cap-sonnet-v2`: Pi wrote 2-3x more output tokens and took 2-4x the wall time (Haiku: 2879 s total against Claude's 661 s). Fixed in `harnesses/gen/make_configs.py`, after which Pi became the fastest arm. **Anyone running Pi on an enterprise gateway needs this flag.**
2. **An empty `CLAUDE_CONFIG_DIR` still loads `~/.claude/CLAUDE.md`.** In `cap-haiku-adaptive`, 2 Claude runs stopped to ask a clarifying question (from a global instruction) and so failed. `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` removes it (verified by asking the model what it loaded). Fixed in the runner.
3. **One hidden test in task 05 demanded an unspecified behaviour** (an explicitly passed history list must be shared, not copied). Every arm that copied it failed. The test now checks only what the prompt specifies. The affected runs were regraded with one grader for all arms (`runs.regraded.jsonl`, `bench/regrade.py`).

## Limits

n=3 per cell, one suite of short Python tasks (under a minute each for Claude), no instructions, hooks, skills or MCP in any arm, so the "full" configs are not tested here. The test laptop was plugged in and fully charged; background load was not controlled. No blinded quality judging was needed: grading is by hidden tests, not by opinion.

## Where each wins

- **Claude Code**: most reliable, has subagents, background tasks, hooks and permissions built in (see FEATURES.md), and is the only one the tested hooks and workflows run on today. It costs the most model context per task.
- **Pi**: fastest wall time, about 8x less context and the lowest CPU and RAM, once `forceAdaptiveThinking` is set. It has no safety layer and no subagents, so anything beyond a plain edit loop has to be built as an extension.
- **OMP**: the most built-in features, but the heaviest and slowest here, with two harness bugs (the SQLite start race and the stdin hang) and a stream stall. No measured advantage over Claude Code on these tasks.
