# Full-config arms, Sonnet 5.5, 2026-10-24

Run data is not published (n=3, the same 10 tasks, thinking medium, jobs 6). Arms: `claude-full` is Claude Code on the tested real Claude Code configuration, with hooks, plugins, skills, MCP and CLAUDE.md. `pi-full` and `omp-full` get CLAUDE.md as AGENTS.md, `~/.claude/skills` and its MCP servers, but none of its hooks, because hooks do not run there. Every full arm's prompt begins with one line: "throwaway session, do not ask".

| arm | passed | total wall s | median context tokens per run |
|---|---|---|---|
| claude-full | 30/30 | 518 | 242k |
| pi-full | 30/30 | 288 | 103k |
| omp-full | 30/30 | 437 | 88k |
| claude-stock (10-23) | 30/30 | 415 | 93k |
| pi-bare-stdin (10-23) | 30/30 | 295 | 12k |
| omp-bare (10-23) | 29/30 | 433 | 50k |

Context is input plus cache read plus cache write.

- **The full configuration does not change task success.** The suite is still at ceiling.
- **The full configuration costs Claude Code about 25% more wall time and 2.6x the context** (242k against 93k per run). The extra context comes from the CLAUDE.md files, the skill listings, the MCP tool schemas and the hook output.
- **Pi's speed survives the full configuration.** It costs Pi no extra wall time, though its context grows 9x, to about the size of stock Claude Code. Pi stays the fastest arm, about 45% less wall time than claude-full.
- Comparing full Pi with full Claude is not like for like: claude-full also runs the large set of hooks. The difference in wall time includes the cost of those hooks.
- Each day's runs were made under that day's background load. The comparison across days (10-23 and 10-24) is indicative only.
