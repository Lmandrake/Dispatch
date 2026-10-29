# Findings: pilot 2026-10-23

Raw data (91 runs) is not published; the tables here are the record. Method: `docs/METHOD.md`. Versions: Claude Code 2.1.292, Pi 1.4.0 (Node 26.12), OMP 18.12.6 (Bun 1.4.4). Model: the env's haiku id on all three. a laptop on battery under heavy background load (load avg 23-32 at start, 5.5 at end; a VM using several cores).

## Verdict

**Supported for Pi, rejected for OMP**, where "Claude Code" means a real configuration (hooks, plugins, skills, MCP).

**Which config "Claude full" is**: every pilot "Claude full" run (15:30-16:00) came after another session's 15:10 plugin trim (another session), so it measured a trimmed plugin set, a set of hooks and two MCP servers. It did not measure the earlier, larger plugin config.

- **Pi: about 2x less local CPU per headless task than Claude Code with the tested config, and about 9x less with the same bare payload. It idles at 0.00% and streams in the TUI with about 4x less CPU than Claude Code.**
- **Claude Code `--bare` costs about the same as Pi bare.** Most of Claude Code's per-task CPU is the tested configuration (a large set of hooks, 3 enabled plugins, MCP servers, ~11 child processes), not the harness, and that is fixable inside Claude Code.
- **OMP is the heaviest harness at the same payload**: 4x Pi per headless task, about 2x Claude Code while streaming in the TUI, and about 1 GB RSS per interactive session. Its idle is low (0.33%).

## Numbers (medians over 3 headless / 2 TUI reps; ranges in SUMMARY.md)

| | Claude full | Claude bare | Pi bare | Pi full | OMP bare | OMP full |
|---|---|---|---|---|---|---|
| headless `pong`, CPU-s | 3.87 | 0.47 | **0.41** | 1.80 | 1.68 | 3.08 |
| headless `tools`, CPU-s | 4.57 | 0.65 | **0.42** | 1.66 | 1.91 | 3.19 |
| headless peak RSS, MB | 423-441 | 210 | **119-134** | 285-308 | 421-436 | 604-616 |
| TUI startup, CPU-s | 4.48 | 1.98 | **0.42** | 1.41 | 1.96 | 3.16 |
| TUI idle, %CPU (45 s) | 1.16 | 0.67 | **0.00** | **0.00** | 0.33 | 0.36 |
| TUI streaming ~400 lines, CPU-s | 1.41 | 1.08 | **0.35** | 0.33 | 2.30 | 2.33 |
| TUI peak RSS, MB | 521 | 385 | **148** | 283 | 968 | 1088 |

Concurrency (`pong`, N started together; CPU-s per agent at N = 1/2/4/8): Claude full 3.58/3.58/3.73/3.86; Pi bare 0.40/0.42/0.43/0.47; OMP bare 1.80/1.67/1.95/1.91; Claude bare 0.41/0.43/0.45, with N=8 at 0.46-0.47 on retry. Per-agent cost is nearly flat to N=8 for all of them: CPU scales linearly and nothing contends at this scale. Summed peak RSS at N=8: Claude full 3.4 GB, Pi bare 1.0 GB, OMP bare 3.5 GB.

## What this means for "more agents on the laptop"

- **Measured**: about 0.4 CPU-s per agent-task for Pi bare against 3.9 for Claude Code as configured. An idle Pi TUI costs nothing; an idle Claude TUI costs about 1.2% of a core (about 12% of a core for 10 parked sessions).
- **Inferred**: for agents mostly waiting on the model, CPU does not limit concurrency today. Neither harness spins while waiting, at least in fresh 45 s windows. Memory is the bigger lever: Pi's 120-150 MB against Claude's 400-520 MB is about 3x more sessions per GB. Reported Claude Code idle and memory drift over hours was **not** tested.
- **Cheapest win without switching harness**: most of the jump from Claude bare (0.47 CPU-s) to Claude full (3.87 CPU-s) is per-invocation config overhead. Trimming hooks that fork interpreters at each event should recover most of it. (Inferred from the bare/full split; no per-hook profile was taken.)

## Trim follow-up (same day, `docs/TRIM-2026-10-23.md`)

Same cells at n=3 on the same model. Config: browser MCP removed; one plugin off (an earlier config change)..

| measure (median) | Claude Code Full | Claude Code Trimmed |
|---|---|---|
| one-line reply, CPU-s | 3.88 | 2.47 |
| small tool task, CPU-s | 4.10 | 3.07 |
| interactive idle, %CPU | 1.09 | 1.23 |
| interactive ~400-line output, CPU-s | 1.26 | 1.67 |
| interactive startup, CPU-s | 4.27 | 3.00 |
| 8 at once, total CPU-s | 30.18 | 20.74 |
| peak memory headless / interactive / 8 at once, MB | 429 / 525 / 3401 | 356 / 495 / 2718 |

Trimming cut per-task CPU by 25-36% and memory by 6-20%. Idle and streaming in the TUI did not improve (within noise at n=3). The bonus "Trimmed+superpowers" run (2.63 / 3.06 / 21.20 CPU-s) shows superpowers costs little; **almost all of the gain is browser MCP**, whose `npx` launch-and-fail ran on every session start. Trimmed Claude Code (2.5 CPU-s a reply) is still about 6x Pi bare (0.41), and its remaining overhead over Claude `--bare` (0.47) is mostly the large set of hooks plus email MCP startup (inferred; not profiled per hook).

## Failures and anomalies

- 1 of 3 Pi bare `stream` headless runs stalled: no output, killed at 240 s, 0.49 CPU-s used. It was a stalled stream, not a spin; the cause is unknown (gateway or Pi).
- Claude bare N=8 failed once: all 8 stalled to the 240 s timeout (about 0.84 CPU-s each). Two immediate retries passed. The likely cause is a gateway hiccup, since all 8 failed together. Recorded, not dropped.
- Claude Code warns `[claude-code:unrecognized_model]` for the gateway's haiku id on 40 of 43 passing runs. Harmless here.
- a browser MCP server MCP fails under Pi and OMP (`npx` can't resolve `chrome-devtools-mcp`). It is the retired route.
- RSS is summed per process (an upper bound; shared pages counted twice).

## Limits

Small N; a busy, battery-powered machine; no `powermetrics` (it needs sudo), so no energy or P/E-core split; 45 s idle windows only; short haiku tasks only. CPU is wait4 rusage over the reaped tree; a 4 Hz psutil tree sample agrees within about 25%.

## Next steps

1. Long idle soak: 10 parked TUIs per harness for 2-4 h, sampling CPU and RSS each minute.
2. `powermetrics` energy per agent: needs a sudo grant or a sudoers rule for `powermetrics` only (a decision for the machine's owner).
3. Per-hook cost in Claude Code: toggle hook groups (and MCP servers) off to locate the remaining ~2 CPU-s gap between Trimmed and `--bare`.
4. A realistic edit-test loop at N = 4/8, with guards ported to Pi extensions / OMP hooks for like-for-like safety.
5. Investigate the Pi stream hang (20x `stream` with `--mode json`).

## Decision 2026-10-25: Pi as delegate worker
The project chose "Wait for harder results": do not build `delegate --harness pi` until the full-config hard-suite run and the lengthened tasks (16-20) are in. Revisit then.

## Decision 2026-10-25: task 20 dropped from the long suite
The project chose "Drop it, run 16-19 now": 20_interpreter_extension timed out at 40 min twice (spec halved); it stays in the repo as an unused draft. Long rerun uses 16-19 only.
