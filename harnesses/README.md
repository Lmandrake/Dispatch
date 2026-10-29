# Harnesses (was NewHarness)

Folded into Dispatch as `harnesses/` on 2026-10-25 by `git subtree`, history kept. The router reads
a local `results/` directory (not published) through `dispatchlib/harness.py` (`bin/delegate harness CLASS`). The frozen task suite is
`benchmarks/capability-suite/`; `bench/tasks/` here is the working copy it was frozen from.


**Hypothesis.** Alternative agent harnesses, **Pi** (`badlogic/pi-mono`, CLI `pi`) and **OMP**
(oh-my-pi, `can1357/oh-my-pi`, CLI `omp`), driving Claude through the same enterprise gateway
Claude Code uses, spend less *local* CPU per agent than the Claude Code CLI, so more agents can
run at once on the laptop.

**Pilot verdict (2026-10-23, `docs/FINDINGS.md`):** true for Pi (about 2x less CPU per task than
Claude Code as configured, 0% idle, about 3x less RAM); false for OMP (heavier than both).
Most of Claude Code's per-task cost is the tested config (hooks, MCP, plugins), not the harness; trimming browser MCP alone cut it by about a third (`docs/TRIM-2026-10-23.md`).

**Capability (2026-10-23, `docs/CAPABILITY-2026-10-23.md`):** on 10 hidden-test coding tasks with the same model, all three pass essentially everything. Pi is fastest (30% less wall time than Claude Code with Sonnet) and sends about 8x less context per task; OMP is slowest and least reliable; Claude Code is the only one with no crash or stall. Pi needs `forceAdaptiveThinking` on an enterprise gateway (now generated). Features from source: `docs/FEATURES.md`.

## Run a harness

    bin/pi-claude                 # Pi TUI with CLAUDE.md, skills, MCP ported from ~/.claude
    bin/omp-claude -p "prompt"    # OMP one-shot
    NH_PROFILE=bare bin/pi-claude # route only, no instructions/skills/MCP

The launchers regenerate config from `~/.claude/settings.json` on every start (base URL, model
ids, apiKeyHelper), so an account change applies to the next run. Nothing names an account.
Binaries are installed under `<agent-storage>/NewHarness/build/` (see `docs/METHOD.md`); override
with `NH_PI_BIN` / `NH_OMP_BIN`. What ports and what does not: `docs/PORTING.md`.
**Warning:** Claude Code's safety hooks do not run under Pi or OMP, and both run tools without
asking.

## Run the benchmark

    python3 bench/cpu_bench.py --out <agent-storage>/NewHarness/runs/<name> --plan pilot --reps 3
    python3 bench/summarize.py <agent-storage>/NewHarness/runs/<name>

The pilot takes about 35 min and a few hundred haiku calls. Copy `runs.jsonl`, `meta.json` and
`SUMMARY.md` into a local results directory.

Capability suite: `python3 bench/capability_bench.py --out <agent-storage>/NewHarness/runs/<name> --model-alias sonnet --arms claude-stock,pi-bare-stdin,omp-bare`, then `python3 bench/cap_summary.py <run>`.

## Layout

`bin/` launchers + `genai-token` · `gen/` route reader and config generator · `bench/` ·
raw data is private · `docs/` LITERATURE, METHOD, PORTING, FINDINGS.
