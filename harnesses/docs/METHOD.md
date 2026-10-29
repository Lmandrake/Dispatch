# Method

## Install (outside ~/dev; agent storage)

- Pi: `npm i @earendil-works/pi-coding-agent@1.4.0` in `<agent-storage>/NewHarness/build/pi/` (Node from Homebrew). Source clone `~/checkout/pi-mono` (reference only).
- OMP: `bun add @oh-my-pi/pi-coding-agent@18.12.6` in `<agent-storage>/NewHarness/build/omp/` (Bun from Homebrew). Two postinstalls (protobufjs) were left blocked; OMP runs without them. Source clone `~/checkout/oh-my-pi`.
- Claude Code: the installed native binary (`~/.local/bin/claude`).

Launchers `harnesses/bin/pi-claude` and `harnesses/bin/omp-claude` regenerate config on every start from `~/.claude/settings.json` (see `docs/PORTING.md`).

## What is measured

`bench/cpu_bench.py`, one JSON line per run in a local `results/<run>/runs.jsonl` (not published), `meta.json` beside it (versions, load average, battery, top processes at start and end).

| Field | Source | Meaning |
|---|---|---|
| `rusage_cpu_s` | `os.wait4` on the harness pid | user+sys CPU of the harness and every descendant it reaped. Primary number. |
| `tree_cpu_s` | psutil, 4 Hz | user+sys summed over the live process tree (last value per pid). Cross-check; misses the tail of short-lived children. |
| `peak_tree_rss_mb` | psutil | peak summed RSS of the tree (double-counts shared pages; an upper bound). |
| `wall_s` | monotonic clock | end-to-end, includes network and model time. |
| `idle_cpu_pct` | psutil over a fixed window | interactive TUI in a 120x40 pty, after a settle period, nobody typing. |
| `prompt_cpu_s` | psutil | CPU in a fixed window after typing one prompt into the TUI (render cost while streaming). |

Local CPU is separated from model latency by construction: CPU-seconds are only accrued while the process actually runs, so waiting on the network costs nothing unless the harness spins. Wall time is reported separately and is not used as a CPU proxy.

## Fairness controls

- Same model on every harness: the env's haiku alias (cheapest; output is short anyway), same gateway, same prompts.
- Token: fetched once by Claude Code's own `apiKeyHelper` outside any measured run, handed to all three harnesses through the same env var (Claude Code via `bin/genai-token` as its apiKeyHelper; refreshed every 15 min). No harness pays for the gateway's own token helper.
- Profiles: `bare` (route only: Claude Code `--bare --strict-mcp-config`; Pi/OMP with no instructions, skills or MCP) is the harness-vs-harness comparison. `full` (an operator CLAUDE.md, skills, MCP, and for Claude Code also hooks and enabled plugins, after a plugin trim) is the "as actually run" comparison. Per-run `--settings` extras: `NH_CLAUDE_EXTRA_SETTINGS`.
- The session's Claude Code env (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, ...) is stripped so children do not think they are nested.
- Configs interleaved within each repetition, so drift in background load hits all harnesses alike.

## Tasks

`version` (startup only, no model call), `pong` (one short reply), `stream` (about 400 lines of output, no tools), `tools` (read two files, write their sum; checked on disk). Each task carries its own pass check; a run that fails its check is reported, never dropped silently.

## Plan (pilot)

3 reps x 6 configs x 4 tasks headless; 2 reps x 6 configs interactive idle (20 s settle, 45 s idle, 40 s after one `stream` prompt); concurrency N = 1, 2, 4, 8 for `pong` on the four configs that matter (Claude full/bare, Pi bare, OMP bare).

## Known limits

- No `powermetrics` (needs sudo; none available), so no energy or P/E-core split. CPU-seconds are not watts.
- The test laptop was busy during the pilot (high load average, a VM, security software that inspects each exec). Every exec costs extra under it; this inflates all harnesses but most those that spawn more processes. Load is logged per run.
- Model/network variance moves wall time and slightly moves CPU (longer streams render more). Pilot N is small; medians and ranges are reported, not significance tests.
- Idle measured over 45 s on fresh sessions; the literature reports Claude Code idle CPU growing over hours, which this pilot does not test.
