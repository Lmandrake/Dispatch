# GitHub survey: how agent setups choose haiku, sonnet or opus (2026-10-20)

Read-only survey of public github.com. Files read directly with
`gh api repos/OWNER/REPO/contents/PATH`. Links assume the default branch (`main`). Where a
file was only seen as a search hit and not read, the row says so.

Coverage limits: `.claude/agents` path
search was not run (the installed `gh` has no `--path` flag). `anthropics/claude-code`,
`anthropics/claude-cookbooks` and `anthropics/skills` were checked at README level only; no
model-assignment guidance was found there. `0xfurai/claude-code-subagents` `agents/python-pro.md`
was not found at that path, so its frontmatter is unverified.

## Table

| repo | file URL | rule they use | stated rationale | evidence offered |
|---|---|---|---|---|
| VoltAgent/awesome-claude-code-subagents (25.9k stars) | https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/README.md (L425-435) | opus = deep reasoning (security-auditor, architect-reviewer); sonnet = everyday coding; haiku = "quick tasks": docs, search, dependency checks | "balancing quality and cost" | none |
| VoltAgent (sample) | https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/categories/01-core-development/backend-developer.md | `model: sonnet` in frontmatter | none beyond README | none |
| wshobson/agents | https://github.com/wshobson/agents/blob/main/docs/agents.md ("Model Selection Criteria") | haiku: "Fast Execution & Deterministic Tasks" (well-specified code, templated tests and docs, deployment ops); sonnet: "Complex Reasoning & Architecture" (architecture, security audits, orchestration); opus for critical architecture and review; fable only where "Opus demonstrably needs multiple attempts" | fable is ~2.6x Opus cost; cost is the stated reason for the fable limit | fable criterion implies a measurement; none cited. The 3 "eval" hits are table descriptions, not evidence |
| wshobson/agents | same file, "Hybrid Orchestration Patterns" | Sonnet architect, then Haiku generates endpoints from the spec, Haiku writes tests, Sonnet reviews | "optimal performance and cost efficiency" | none |
| wshobson/agents | https://github.com/wshobson/agents/blob/main/tools/adapters/capabilities.py | adapter maps aliases per harness; `bare_model_aliases` flag | portability | none (code, not policy) |
| Chachamaru127/claude-code-harness | https://github.com/Chachamaru127/claude-code-harness/blob/main/docs/model-routing-policy.md | routes by role tier, not prompt text: `lite` (Haiku 4.5 for lightweight reading), `standard`, `worker`, `deep`, `review`; "do not infer effort from free-text markers" | durable routing belongs in config and frontmatter, not prompt inference | it says "benchmark results do not justify raising every role's effort" but cites no benchmark and links none. Official docs only |
| kkkman22/Forge | https://github.com/kkkman22/Forge/blob/main/docs/opusplan-guide.md | `opusplan`: opus in plan mode, sonnet in execution | reasoning-heavy planning vs code generation | claims 20-40% cost saving with no data shown |
| AbrarFaiyad/Claude-Token-Optimization-Setup | https://github.com/AbrarFaiyad/Claude-Token-Optimization-Setup/blob/main/stages/02-opusplan/README.md | opusplan (opus plans, sonnet executes file reads and tool calls) | "most calls are execution-flavored"; Sonnet is "less verbose per call" | an experiment plan (3 runs, look at ccusage) with no results in the file. Hypothesis, not measurement |
| bcorey85/dotfiles | https://github.com/bcorey85/dotfiles/blob/main/claude/.claude/scripts/agent-model-guard.sh | PreToolUse guard: blocks call-site `opus` and `inherit`; empty model allowed only if the agent file pins one | "silent Opus inheritance" fans out Opus from an Opus orchestrator | none. Guard, not a policy |
| dbc-oduffy/claude-klabauter | https://github.com/dbc-oduffy/claude-klabauter/blob/main/coordinator_core/hooks/block_ungranted_opus_subagent.py | Hard-deny Opus-tier subagents unless the persona pins opus or the PM grants it | cost and PM control | the module docstring cites an audit that measured five dispatches inheriting Opus. That is a measurement of a leak, not of quality |
| rezarajan/platformctl | https://github.com/rezarajan/platformctl/blob/main/scripts/hooks/guard-agent-model.sh | Spawns must pass explicit sonnet or haiku, or use a project agent pinned to one | "tokens never burnt on a big-model agent by accident" | none |
| Manolii-org/ai-starter-pack | https://github.com/Manolii-org/ai-starter-pack/blob/main/scripts/lint-agent-routing.py | lint: a LiteLLM proxy silently reroutes the `haiku` alias to OSS providers, and an escalation can land on Opus pricing | routing correctness and cost leak | cites an internal report (`master/reports/explore-opus-regression-fix-2026-07-12.md`), not read |
| anthropics/claude-cookbooks | https://github.com/anthropics/claude-cookbooks/blob/main/multimodal/using_sub_agents.ipynb (also listed as anthropic-cookbook) | Opus orchestrator writes a prompt for each Haiku sub-agent that reads PDF pages; Haiku extracts, Opus answers | Haiku for bulk extraction of tables, Opus for synthesis | none. Uses Claude 3 Haiku and Opus 4.8 ids |
| 0xfurai/claude-code-subagents | https://github.com/0xfurai/claude-code-subagents (README L7) | "configured with specific Claude models based on task complexity" | cost-effectiveness | claim only. Per-agent frontmatter not verified |
| rshah515/claude-code-subagents | README | no model rule found | n/a | n/a |
| anthropics/claude-code, anthropics/skills | README level only | no per-agent model rule found | n/a | n/a |
| RouteLLM (lm-sys/RouteLLM, 5.6k stars) | https://github.com/lm-sys/RouteLLM | learned router between strong and weak models (search result only, not read) | cost-quality tradeoff | not read in this survey; it is a paper-backed router, not a Claude Code rule |

## Tally (12 rules or policies with a stated basis, from 12 sources)

Each rule may cite more than one basis, so the counts overlap.

- Task simplicity or type (opus = deep reasoning, haiku = mechanical or well-specified): 6 of 12 (VoltAgent, wshobson, Chachamaru, Forge, AbrarFaiyad, cookbook). This is the dominant basis.
- Checkability or verifiability (Haiku only where the output is checked): wshobson's Haiku criterion ("well-defined specs") is partly this. Total 0 to 1.
- Cost: 8 of 12 (VoltAgent, wshobson fable, Forge, AbrarFaiyad, the three guards, Manolii, klabauter). Cost is the stated reason for most guards.
- Latency: 1 explicit (wshobson "fast execution").
- Measurement cited as a basis for the rule: public github.com repos: 0 cite a measurement of quality. The closest are Chachamaru ("benchmark results", unlinked) and wshobson's fable criterion ("demonstrably needs multiple attempts", unsourced).
- Evidence is claimed but not shown: Forge (20-40% saving), AbrarFaiyad (planned ccusage run), 0xfurai (claim only).

Summary: on public GitHub, model tiers are set by task type and cost, and almost none is backed by a measurement. No rule in this survey gates Haiku on agreement with a reference rather than on task type.
