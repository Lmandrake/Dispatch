# Literature review: do Pi / OMP use less local CPU than Claude Code?

Compiled 2026-10-23. Sources fetched via Fetcher or `gh` unless marked UNVERIFIED. Local clones read:
`~/checkout/pi-mono` (136b87e), `~/checkout/oh-my-pi` (0b5c27ab).
Bottom line up front: there is **no published CPU/RAM benchmark of Pi or OMP vs Claude Code** that I could find.
The case for the hypothesis rests on Claude Code's documented idle/render CPU bugs plus Pi/OMP's simpler design.

## 1. Why Claude Code CLI has been CPU-heavy (reported)

All numbers below are user reports in issues, not Anthropic measurements.

| Issue | State | What it reports |
|---|---|---|
| [#22509](https://github.com/anthropics/claude-code/issues/22509) High CPU at idle/prompt | open | v2.1.29 macOS 20%+ CPU at a fresh prompt. A later comment (v2.1.39, M1 Pro 16", `powermetrics` 10 s): two idle sessions each at ~989 CPU ms/s (one full P-core), ~10.6 W CPU package power for the pair, "Energy Impact" ~4000 each. `sample` shows the main thread never leaves `uv__io_poll -> TLSWrap::ClearOut -> RunMicrotasks` (microtask loop spin). Another commenter: 3 idle processes ~100% each drained battery in a day; 134 orphan subagents were the cause for one user. Another (Linux, v2.1.29): `strace` shows ~2,152 `madvise`/s, argued to be Bun GC stuck in a loop at 1.78 GB RSS. |
| [#22275](https://github.com/anthropics/claude-code/issues/22275) ~100% per instance idle | closed | Two instances at ~100% each on a 4-core Linux box, v2.1.29. Closed (locked); 4-core machine "noticeably sluggish". |
| [#19393](https://github.com/anthropics/claude-code/issues/19393) High CPU (100%+) when idle, v2.1.12 | open | WSL2: one instance 105-130%, another 59-70%. A comment says it still happens at v2.1.272 (Fedora). |
| [#88914](https://github.com/anthropics/claude-code/issues/88914) Idle sessions burn 0.3-5% CPU because timers trigger GC | open | The most careful measurement (/proc, 30 s windows, v2.1.240, native Bun/JSC build, Linux): pristine config 0.30-0.76%, typical config (plugins, hooks, 1 MCP) 1.46%, 15-hour session 4.4-5.0% with 671 MB RSS vs 472 MB at 1 h. "Ten idle sessions ~15% of a core." Shows the problem is smaller on recent builds (a few percent, not 100%). |
| [#95306](https://github.com/anthropics/claude-code/issues/95306) Idle TUI CPU scales with number of installed skills | open | Windows, bisected: bare config 1.0% idle; 40 user skills 4.9%; full config 11-15% and 3-4.6k "other" I/O syscalls/s; about 45 syscalls/s per skill dir. Relevant to any setup with many skills. |
| [#4953](https://github.com/anthropics/claude-code/issues/4953) Memory leak to 120+ GB | open | v1.0.53 on 128 GB Linux. Recent comments: six concurrent sessions on a 24 GB Apple-silicon Mac (v2.1.201) each at 12.8-15.7 GB RSS, jetsam killed all; another user sees 180 MB (v2.1.215) vs 11 GB (v2.1.159), speculated to relate to the Bun Rust port (speculation, not an Anthropic statement). |
| [#22042](https://github.com/anthropics/claude-code/issues/22042) Memory regression 2.1.27 | closed | 467 MB to 7.5 GB in 20 s after typing one word; 2.1.25 stable at ~540 MB. |
| [#10881](https://github.com/anthropics/claude-code/issues/10881) Degrades over long sessions | open | Minutes between requests after several autocompacts. Cause unproven. |
| [#769](https://github.com/anthropics/claude-code/issues/769), [#1913](https://github.com/anthropics/claude-code/issues/1913), [#826](https://github.com/anthropics/claude-code/issues/826), [#3648](https://github.com/anthropics/claude-code/issues/3648) flicker / scrollback | #769, #826 open | Long-running flicker/scroll-jump threads (307, 354, 187, 337 comments). Flicker is a symptom of full-redraw Ink rendering. |
| [#5771](https://github.com/anthropics/claude-code/issues/5771) 100% CPU and memory | open | Windows, v1.0.80, during builds (likely child processes; not a TUI cost). |

Search also surfaced a changelog line (UNVERIFIED version; seen only as a search snippet at
<https://code.claude.com/docs/en/changelog>): "high CPU usage: a busy loop in long-running idle sessions no longer pins a CPU core".
So Anthropic has been fixing idle spins release by release; the number to measure is the current build, not 2.1.29.

### Anthropic statements on the renderer

- Chris Lloyd (Claude Code TUI engineer), Hacker News, <https://news.ycombinator.com/item?id=46701013>: they "rewrote our rendering system from scratch" as a differential renderer, shipped to everyone; ~1/3 of sessions still see at least one flicker. Pipeline per frame: React scene graph -> layout -> rasterize to 2D screen -> diff vs previous -> ANSI; "~16 ms frame budget so roughly ~5 ms" for scene graph to ANSI; "closer to a small game engine" than a TUI. Perf problems he names: no `<Static>`, so larger trees re-render more often and caused GC pauses (fixed by memoization); screen buffer moved to packed TypedArrays because double-buffer blits caused "large GC pauses", "order of seconds on slower machines".
- Fullscreen mode docs, <https://code.claude.com/docs/en/fullscreen> (research preview): alternate screen buffer, "only renders messages that are currently visible", "memory stays constant regardless of conversation length", sends only changed cells. Switch with `/tui fullscreen`.
- Secondary: [dev.to summary](https://dev.to/gabrielanhaia/why-claude-code-flickered-dec-mode-2026-cell-diffs-and-a-16-ms-frame-budget-5abd) (dates the rewrite announcement 2025-12-17, rollback, re-rollout 2026-01-21); [Peter Steinberger, "The Signature Flicker"](https://steipete.me/posts/2025/signature-flicker) (snippet only: Ink lacked fine-grained incremental updates; not fully read).
- Runtime: current native builds run on Bun (JavaScriptCore) per #88914 (`/$bunfs` in the #22509 stack trace); older npm builds ran on Node/V8 (#22509 powermetrics shows `node (claude)`). So "Node, Ink/React" in the hypothesis is out of date: it is Bun + a custom Ink-derived renderer with React reconciliation.

Takeaway: the TUI is a React scene graph with a rasterize-and-diff loop, GC-sensitive, plus idle timers/file-system scans (skills, plugins, LSP, watchers). Streaming-time cost is real; idle cost is a bug class that varies by version and config.

## 2. Pi / OMP design claims

Pi (Mario Zechner), <https://mariozechner.at/posts/2025-11-30-pi-coding-agent/> (fetched, read):
- Did not want "to write my TUI like a React app"; rejected Ink, Blessed, OpenTUI.
- pi-tui is "simple retained mode": components have `render(width) -> string[]`, cache their output (a fully streamed message is not re-parsed), then "only redraws what changed" (differential), wrapped in synchronized output (CSI ?2026h/l). Keeps the whole scrollback's lines in memory: "a few hundred kilobytes for very large sessions". Native scrollback, no alt screen.
- Says it "still flickers less than Claude Code" in VS Code's terminal. No CPU numbers given. His performance statement is "not a big deal" on modern machines.
- Minimal system prompt: "system prompt and tool definitions together come in below 1000 tokens" (blog). Four core tools. Argues frontier models are RL-trained enough not to need big prompts.
- Terminal-Bench 2.0 with Opus 4.5: accuracy benchmark only, not resource use.
- Repo claim, `~/checkout/pi-mono/packages/tui/README.md`: "differential rendering", updates "only changed lines or viewport rows", synchronized output. Runtime: Node.js.
- Token overhead, third-party: [TestDino harness overhead benchmark](https://testdino.com/blog/harness-overhead-benchmark) (2026-10-08, 3 runs, median, headless): first-call input tokens Claude Code 2.1.293 = 31,480 (clean profile), Cursor CLI 13,174, Pi 0.73.1 = 1,894 (range across 11 agents 1,894-31,798). Tokens, not CPU. Different default models per agent. Matters for API cost/latency and cache, not local CPU.

OMP (oh-my-pi), `~/checkout/oh-my-pi/README.md` and `packages/tui/README.md` (read locally):
- Fork/derivative of Pi; own pi-tui with "three-strategy" differential rendering and CSI 2026. Runtime Bun plus ~80k lines of Rust N-API natives (grep, glob, shell, PTY, image, syntax highlighting).
- Claim ("Unapologetically native"): ripgrep/glob/find run in-process, bash via embedded "brush" with 58 utilities in-process, "zero fork/exec". That removes subprocess cost for tool calls, which is local CPU, but no numbers are given.
- I found **no quantified performance, startup or memory claims** in the OMP README or docs (grep for startup/cpu/faster/memory hit only config text and an MCP 250 ms startup gate in `docs/mcp-runtime-lifecycle.md`). OMP ships a lot more features (31 tools, LSP, DAP, eval, subagents), which can cost CPU. Web search for OMP benchmarks returned nothing.

## 3. Benchmarks of harness overhead and many-agents experience

- No benchmark found comparing CPU-seconds or RSS of Claude Code vs Pi vs OMP vs opencode vs codex. Web searches (Fetcher, 2026-10-23) returned mostly token/accuracy comparisons (TestDino above; others in the result list, e.g. nimbalyst, tensorlake, alongside.team, unread and UNVERIFIED). Treat the gap as real: our own measurement is the contribution.
- opencode (Bun/Zig TUI) has its own idle-CPU history, so "alternative harness" is not automatically lighter: [#42306](https://github.com/anomalyco/opencode/issues/42306) main thread ~100% redrawing a spinner at ~15 fps with no output; [#811](https://github.com/anomalyco/opencode/issues/811) idle TUI 25-30% of a Xeon; [#6172](https://github.com/anomalyco/opencode/issues/6172) RSS 1.2 GB retained; [#25490](https://github.com/anomalyco/opencode/issues/25490) 4.1 GB process group. (From search snippets; not fully read.)
- Many concurrent Claude Code sessions, what bottlenecked: RAM, not CPU, on a 24 GB Mac (#4953: six sessions, ~86 GB RSS requested, jetsam); idle CPU summed across sessions (#22509: three at ~100%; the 10-session M3 Max report in #22509 comments, 667% total); battery/thermals (#22509 power numbers); orphaned subagents/background processes (#22509 comment, [#72308](https://github.com/anthropics/claude-code/issues/72308) title only). Local child processes (tsc, builds, watchman) can dominate and are harness-independent.
- Nothing found on Pi or OMP running many concurrent agents. UNVERIFIED either way.

## 4. Measurement methodology (macOS)

Sources fetched: `powermetrics(1)` <https://keith.github.io/xcode-man-pages/powermetrics.1.html>; Apple Energy Efficiency Guide
<https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/MonitoringEnergyUsage.html>
(search snippet plus a mirror fetch of the Introduction). The rest of this section is standard practice from general knowledge, marked (K); verify on this machine before relying.

- Compare **CPU-seconds (user+sys) over the whole task**, not %CPU snapshots. A run's cost = integral of CPU use; %CPU depends on sampling window and wall time. Report CPU-seconds per completed task plus wall time and peak RSS. (K)
- Exact accounting: run the harness under `/usr/bin/time -l` (BSD time: user, sys, max RSS, involuntary context switches) or a wrapper using `wait4()`/`getrusage(RUSAGE_CHILDREN)`. Caveats: only counts descendants that were waited on (orphaned/daemonized children are lost); max RSS on macOS is bytes. (K)
- `ps -o cputime`/`%cpu` caveat: macOS `ps %cpu` is a decaying average over process lifetime (not the current rate), so it misleads; prefer `cputime` deltas or `top -l 2 -stats pid,cpu,time` (second sample is a true interval). (K)
- Process trees: sample the whole tree (harness plus bash/rg/git/LSP/MCP children), and also separate "harness process" from "tool children", since OMP moves tool work in-process while Claude Code forks it. Total tree CPU is the fair number; harness-only CPU is the diagnostic one. (K)
- `powermetrics` (root): `--samplers tasks --show-process-samp-norm` shows per-process CPU ms/s normalised to the sample window; `--show-process-coalition` groups by coalition; `--show-process-energy` gives an "Energy Impact" proxy that the man page calls a rough proxy; also reports interrupt/package-idle wakeups, which matter for idle timers (man page, above). #22509 used exactly this at 10 s.
- Apple Silicon: P vs E cores. CPU-seconds on an E-core are not equal to P-core seconds; background/low-QoS threads get E-cores. Record cluster residency/frequency (powermetrics `cpu_power` sampler) or report package power (mW) alongside CPU-seconds. Thermal/battery state changes frequency; run on AC, same power mode, cool start, nothing else running. (K)
- Fair harness comparison (K): same model and snapshot; identical task script (replayed or deterministic prompts); separate network wait from local work by reporting CPU-seconds, not wall time, and by also running an **idle-at-prompt** phase and a **streaming-only** phase (fixed long output, no tools); pin a mock/recorded API server (same SSE stream replayed) to remove model variance entirely; warm-up run discarded (JIT, disk cache, first-run config writes); N>=5 repetitions, report median and spread; identical tool set and system prompt size where possible, or report both default and normalised configs; same terminal emulator and size (render cost depends on it); record harness version and runtime (Bun/Node). Token-overhead differences (section 2) confound task-level comparisons because larger prompts mean more JSON/SSE handling and cache effects; note them.
- Concurrency test: N agents x harness, measure aggregate CPU-seconds/s, total RSS, and power over a fixed window; find N at which the machine saturates (or swaps).

## Verdict

**Plausible, with a caveat on size and a bigger caveat on what counts.**

Reported (evidence): Claude Code has a long, documented history of high idle and streaming CPU and memory growth (#22509, #19393, #22275, #4953), including a measured ~1 core and ~5 W per idle session on an M1 Pro in v2.1.39 and a pipeline Anthropic itself describes as a game-engine-like React-to-ANSI frame loop with GC trouble. Idle cost also scales with skills/plugins (#95306), and a setup with many skills has many.

Reported but improving: the most recent measurement (v2.1.240, #88914) is 0.3-1.5% idle CPU per fresh session and ~5% after 15 h, and a changelog line (unverified) says an idle busy loop was fixed. If the current build idles at a few percent, the idle gain from switching is small in absolute terms: roughly 10 sessions ~ 15% of one core, i.e. not what limits concurrency.

Inferred (not measured anywhere I found): Pi's and OMP's differential line-diff renderer with cached components should be cheaper per streamed token than a React reconciliation plus rasterize plus diff, and a sub-1k-token prompt reduces request size, but both are still JS (Node / Bun) with GC. OMP's in-process tools remove fork/exec but add a large feature surface. Expected gain, my estimate only: during active streaming, a modest constant factor (perhaps 1.5-3x less harness CPU); at idle, near parity vs a current Claude Code build with a lean config, large win vs a buggy build. Memory (RSS per agent) and avoiding the multi-GB growth are likely the more important limit for many agents on a laptop (#4953), and tool child processes (builds, tsc, watchman) will dwarf either harness.

Therefore the experiment to run is: current Claude Code (default and fullscreen, lean skills config) vs Pi vs OMP, same model via a replayed SSE server, three phases (idle, streaming, tool-heavy), CPU-seconds over the process tree plus peak RSS and powermetrics package power, N>=5, then a concurrency ramp. The hypothesis should be accepted or rejected on those numbers, not on the anecdotes above.

## Source quality notes

- Fetched and read: Zechner blog; HN 46701013; Claude Code fullscreen docs; TestDino; issues #19393, #22275, #22509, #88914, #95306, #4953, #22042, #10881, #769 (bodies and selected comments via `gh`).
- Seen only as search snippets (not fully read): Steinberger post, opencode issues, dev.to details beyond first screen, changelog idle busy-loop line, #72308, #5771 comments.
- Not found: any CPU/RAM benchmark of Pi or OMP; OMP performance claims; Pi concurrent-agent reports.
- Built-in WebSearch unavailable; Fetcher search engines fell back to DuckDuckGo/OpenAlex for some queries, so coverage is partial.
