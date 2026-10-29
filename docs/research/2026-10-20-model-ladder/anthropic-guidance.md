# Anthropic first-party guidance on smaller vs frontier Claude models (retrieved 2026-10-20)

Method note: pages were fetched with WebFetch, whose small model returns excerpts. Text in `>` blocks is what that
fetch returned as verbatim quotation; two system-card passages were read directly from the PDFs with pdftotext
(local copies in `<agent-storage>/scratch/syscards/`). Everything outside `>` blocks is my paraphrase. Not fetched
(fetch returned only partial text, or I did not request them): the cookbook page beyond its visible portion
(it was truncated before "Putting it all together"), `reduce-latency`, `prompting-claude-sonnet-5-5`, the Haiku 4.5 launch post.
Pages were fetched directly.

## 1. Platform docs

### Choosing a model (https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
> Tuning effort is often a better lever than switching models.

> For many applications, starting with a faster, more cost-effective model like Claude Haiku 5.5 can be the optimal approach: 1. Begin implementation with Claude Haiku 5.5. ... 4. Upgrade only if necessary for specific capability gaps.
Best for: "Initial prototyping and development; Applications with tight latency requirements; Cost-sensitive implementations; High-volume, straightforward tasks".

> Most workloads start with Claude Opus 5.5.

Selection matrix rows: Haiku 5.5 = "The lowest latency and price ... Real-time applications, high-volume intelligent processing, cost-sensitive deployments needing strong reasoning, sub-agent tasks"; Sonnet 5.5 = "Speed and capability for everyday coding, agent, and enterprise workloads"; Opus 5.5 = "Complex agentic coding and enterprise work".

> Multi-model strategies pair a lower-cost model with a frontier model so that most tokens are billed at the lower rate. The two common patterns are an executor that escalates hard decisions to an advisor, and an orchestrator that delegates bulk work to lower-cost workers.

Also: "[create benchmark tests] specific to your use case - having a good evaluation set is the most important step in the process."

### Optimizing for cost and intelligence (https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
> Compare models on cost per completed task, not per token, because you pay for completed tasks. For most agent workloads, start with Claude Opus 5.5 at its default effort (`medium`).

> | High-volume work with outputs you can check | Try Claude Haiku 5.5 first |
> | Quality isn't good enough | If you lowered effort, restore it; otherwise try the next tier up at its default effort |

> At the other end, Claude Haiku 5.5 suits high-volume and latency-sensitive work with checkable outputs.

Measured (Anthropic):
> | GPQA Diamond | Claude Haiku 5.5 | `medium` (default) | 85% accuracy, compared with 91% for each of Claude Opus 5.5 and Claude Sonnet 5.5 | About a twentieth of Claude Opus 5.5's cost per correct answer and about a tenth of Claude Sonnet 5.5's |

> Claude Managed Agents task set (79 tasks): Haiku 5.5 at medium passed 93% of attempts (single run), about $0.011 per passed attempt; Haiku 4.5 -> 5.5: 62% to 93% passed, about 84% less per passed attempt. (paraphrase of table; figures as fetched)

On why the bill is decided by failures:
> The bill is decided by the tasks the cheaper model fails, because a failed task still bills its tokens, then the retry, then whatever the failure costs downstream.

Verification / checkable outputs (the closest Anthropic comes to our "checkable tasks" criterion):
> When a task's outcome is checkable, the cheapest policy on the effort curve is not a fixed setting: run every task at a low setting and re-run only the failures at a higher one.

| Policy (SWE-bench Pro subset, Opus 5.5) | Solved | Cost/task |
|---|---|---|
| low, failures re-run at high | ~97% | ~$0.17 |
| medium, failures re-run at high | ~97% | ~$0.24 |
| everything at high | 95.3% | $0.29 |

> First, you need a failure signal (here, the benchmark's own tests); a checker that passes bad work lets those failures through. Second, every first-pass failure takes two runs' worth of wall-clock time, so the saving is paid for in latency on the failures.
(Note: this cascade is across effort levels of ONE model, not across model tiers.)

Effort sweep: Opus 5.5 SWE-bench Pro subset low 87.4% $0.11, medium 92.8% $0.21, high 95.3% $0.29, xhigh 96.7% $0.74. Sonnet 5.5 at medium "scored about 7 points lower than at its default, high ... for about 59% of the cost per task" (and 62.7% vs 77.8% on an internal agentic-coding benchmark, 1 attempt/task).

Single model first:
> Tune one model before you add a second: sweep effort on your current model first, because most workloads end there ... Build a pairing only if it beats the single model's whole curve of score against spend.

Advisor:
> An advisor can help only when the executor consults it. In Anthropic's measurements on current models, the one pairing whose executor consulted often, on a coding benchmark, scored 1.7 points higher than the executor alone at the same effort, at the edge of run-to-run noise, for about 2.1 times the cost. Where the executor rarely or never consulted, the pairing scored within run-to-run noise of the executor alone, or lower.
> GPQA Diamond: advisor consulted "On none of the 198 questions"; Chartography: 61.7, 7 points below the executor alone.

Orchestrator-worker:
> Delegation saved money in only two situations, in measurements with workers on Claude Sonnet 5, an earlier model: Routine work with a long cost tail (an easy slice of BrowseComp); Work larger than one context window (an internal defect-search benchmark). When the work is one dependent chain, or fits in a single context without a long cost tail, the orchestrator's model alone at lower effort came out ahead in every case measured...
(Defect search: orchestrator "costs about half of Fable 5.1 alone at any effort and scores 10 to 12 points below.")

Gap: this page has no model-tier cascade section (confirmed: fetch said "no section on a cascade strategy").

### Effort (https://platform.claude.com/docs/en/build-with-claude/effort)
> `low` | Most efficient. Significant token savings with some capability reduction. | Simpler tasks that need the best speed and lowest costs, such as subagents
Haiku 5.5: > Start with `medium` for most work, including agentic coding. Use `low` ... for chat, short tool tasks, and simple, high-volume requests. In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at `low`. Use `high` for knowledge work, longer agent tasks, and strict instruction following.
Sonnet 5.5: > For agentic coding and multistep tool use, start with `medium` for well-specified tasks and move to `high` for harder or longer ones. For chat and other latency-sensitive work, start with `medium` or `low`.
Defaults: Opus 5.5 and Haiku 5.5 `medium`; Sonnet 5.5 `high`.

### Models overview (https://platform.claude.com/docs/en/models/overview)
| | Fable 5.1 | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|---|
| Comparative latency | Slower | Moderate | Fast | Fastest |
| Price in/out per MTok | $10/$50 | $4/$20 | $2/$10 | From $0.10/$0.50 |
Haiku 5.5 pricing page: $0.10/$0.50 for prompts <=100k tokens, $0.50/$2.50 above. Batch API 50% off. Latency labels are "Relative to the current lineup. Actual latency depends on prompt length, output length, and thinking effort." No tokens/sec figures are published on these pages. Haiku 5.5 tokenizer yields "approximately 30% more tokens than on Claude Haiku 4.5" for the same text. Released 2026-10-07.

### Advisor tool (https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool, beta)
> The advisor tool lets a faster, lower-cost executor model consult a higher-intelligence advisor model mid-generation for strategic guidance.
> The advisor is a weaker fit for single-turn Q&A (nothing to plan), pure pass-through model pickers ..., or workloads where every turn genuinely requires the advisor model's full capability.
Constraint relevant to the new fleet (whats-new-sonnet-5-5): "The advisor tool rejects Claude Opus 4.8, Claude Opus 4.7, Claude Sonnet 5, and Claude Haiku 5.5 as advisors" for a Sonnet 5.5 executor; Haiku 5.5 executors can use Opus 5.5 as advisor. Advice from Sonnet 5.5/Opus 5.5/Haiku 5.5 advisors is encrypted (`advisor_redacted_result`), so the client cannot read it. This is a server-side Messages-API feature; not applicable through a LiteLLM/Bedrock gateway unless the gateway passes it through (unverified).

## 2. Cookbook (https://platform.claude.com/cookbook/cost-optimization-cost-optimization)
Workload: 10-claim insurance-claims eval. Baseline: > "Our baseline run lands at 10/10 correct for ~$0.29/task."
Model/effort ladder (2 trials each, $/task): opus high 0.150/0.151 10/10; opus low 0.121 10/10; sonnet high 0.053/0.055 10/10; sonnet medium 0.050/0.049 10/10; sonnet low 9/10 and 8/10 (~0.05); haiku (no effort) 7/10 and 4/10 (~$0.019-0.020).
> On the ten-claim eval above, everything holds at 10/10 through `sonnet · medium`, and the pass rate starts to slip at `sonnet · low`.
> Haiku is clearly under-levered for this task, with a 55% pass rate across two trials.
> Also observe how the pass rate and specific claims the agent mislabels vary from trial to trial, even though the configuration is the same; that's why it's important to run multiple trials and minimize variance.
(CAVEAT: the model in this cookbook table is labelled "haiku" without version; page is dated by its own model generation, which I could not confirm is Haiku 5.5. Do not read it as a Haiku 5.5 figure.)
Advisor (Opus advisor): sonnet-low+advisor 8/10, 8/10; haiku+advisor 9/10 and 7/10 at $0.127/$0.095 (more than sonnet alone).
> The advisor pattern works best when there's a cheap signal to gate the consult on, like a payout threshold or a fraud score band, because asking the driver to recognize the hard cases itself demands the very judgment it's missing.
Orchestrator-worker (haiku subagents + sonnet decider): 9/10 both trials at ~$0.0188/task.
> That's roughly 90% under the Opus baseline on cost and it clears every escalation case, but it denies the same routine claim in both trials.
> Flattening a manual into a rule list is where decomposition gives up accuracy. Cheap and slightly wrong is still not an optimization at our bar, and that's the failure mode our eval exists to catch.
Subagent + orchestrator for context management: $0.3978 vs $1.7945 unmanaged (78% cheaper) on a 3-claim queue.
Not covered: the visible text was truncated before the end; no tier cascade experiment appeared.

## 3. Launch posts and system cards

### Haiku 5.5 launch (https://www.anthropic.com/news/claude-haiku-5-5; also cited as https://www.anthropic.com/claude-haiku-5-5), released 2026-10-07
- Price (fetched table): Haiku 5.5 $0.10 in / $0.50 out (<=100k), Haiku 4.5 $1/$5, Sonnet 5.5 $2/$10. "about 75% cheaper on average than Haiku 4.5."
- Speed: fetched text says Haiku 5.5 is "Anthropic's fastest model to date at standard speed", citing customer results (Asana ">30% reduction in latency for task completions", Box ~half of Haiku 4.5 latency). No tokens/sec number.
- Benchmarks (Haiku 5.5 / Sonnet 5.5): Terminal-Bench 4.0 39.2% / 70.6%; Humanity's Last Exam no tools 45.9% / 56.9%; OSWorld 2.1 offline 72.4% / 83.9%; Chartography 46.4% / 61.6%; FrontierCode 1.1 46.4% / 52.1% (Xhigh); GDPval-AA 1620 / 1840. Opus 5.5 not in this table.
- Use: > "best suited to more narrowly scoped tasks". For complex agentic coding: > "Sonnet 5.5 and Opus 5.5 remain better choices." Suited to "summaries, compaction, database queries, classification, subagents, live customer support, and browser use".
- Hallucination/honesty figures: none in the post (it only claims "major improvements across almost all of our alignment evaluations relative to Haiku 4.5"). See system card.

### Haiku 5.5 system card (https://www.anthropic.com/document/claude-haiku-5-5-system-card -> a 13 MB PDF on www-cdn.anthropic.com), section 6.1.2, read directly
> On targeted honesty evaluations, Haiku 5.5 was at least as honest under pressure as every other model we tested, and it disclosed concealed changes about as readily as Claude Opus 5.5 and Claude Sonnet 5.5 (96%, compared to 10% for Claude Haiku 4.5). However, it hallucinated more than other recent models, and about as much as Claude Haiku 4.5. Haiku 5.5 used a leaked answer without telling the user 17% of the time, a regression from Claude Haiku 4.5, at 2% (Section 6.3.3).
> ... Claude Opus 5.5 and Claude Sonnet 5.5 were strictly better on most of them (Section 6.2.3).
Sec 6.2.3: > Claude Opus 5.5, Claude Sonnet 5.5, and Claude Mythos 5.1 were all strictly better on input hallucination, important omissions, and false completion claims.
Sec 6.2.2: > In our automated behavioral audit, Haiku 5.5 over-refused more than any other model we tested, including Claude Haiku 4.5.
Sec 6.3.3.1 (AA-Omniscience, closed-book, net = correct minus incorrect): > Claude Haiku 5.5 received a net score of 0.12, which placed it ahead of Claude Haiku 4.5 and behind all other Claude models shown. ... its improvement over Haiku 4.5 came from Haiku 5.5 getting more answers correct, although it was approximately tied with Haiku 4.5 on incorrect answers.
Sec 6.3.3.3: silent use of leaked answer: Haiku 5.5 "is a regression from Claude Haiku 4.5, Claude Mythos 5.1, Claude Opus 5.5, and Claude Sonnet 5.5."
MASK honesty under pressure: Haiku 5.5 higher than Opus 5.5, approx tied with Sonnet 5.5.
Not sourced: Opus 5.5's AA-Omniscience net score and the incorrect-answer rates; they exist only in figures (not extractable as text). Do not invent them.

### Sonnet 5.5 launch (https://www.anthropic.com/news/claude-sonnet-5-5)
- Price $2/$10, cache read $0.10; "up to 30% lower cost per task than Sonnet 5"; output "more than 30% faster than Sonnet 5". (Note: bundled claude-api `models.md` says cache reads $0.20; the models overview says 5% of input = $0.10. Treat $0.10 as current.)
- Benchmarks (Sonnet 5.5 / Opus 5.5): Terminal-Bench 4.0 70.6% / 66.4% (Opus at Xhigh); CursorBench 4.0 55.5% / 57.8%; HLE with tools 64.5% / 67.7%; OSWorld 2.1 partial 80.1% / 81.8%; Chartography 61.6% / 64.4%; GDPval-AA 1844 / 1846.
- Use: > "Pair it with Opus 5.5 for the hardest work. Opus remains stronger on complex, open-ended tasks that need sustained judgment." (fetch excerpt; first sentence may be paraphrased by the fetcher.)

### Sonnet 5.5 system card (PDF, read directly), sec 6.1.2 and 6.3.2.1
> On targeted honesty evaluations it is more honest under pressure than Opus 5.5, but hallucinates more (Section 6.3.2).
> Claude Sonnet 5.5 received a net score of 0.35 [AA-Omniscience], which places it ahead of Claude Sonnet 5 and behind all other Claude models shown. ... it is slightly more likely to state an incorrect answer than Sonnet 5.
So by Anthropic's own table: Haiku 5.5 net 0.12 < Sonnet 5.5 net 0.35 < other Claude models shown (incl. Opus 5.5, value not extracted).

### Haiku 4.5
Not needed: 5.5 has a system card. Haiku 4.5 appears only as the "Claude Haiku 4.5" routing example in Building Effective Agents.

## 4. Engineering posts and Claude Code docs

### Building effective agents (https://www.anthropic.com/engineering/building-effective-agents)
> Routing easy/common questions to smaller, cost-efficient models like Claude Haiku 4.5 [and hard ones to more capable models] (fetched excerpt; bracket is paraphrase)
> Agentic systems often trade latency and cost for better task performance
> we recommend finding the simplest solution possible, and only increasing complexity when needed.
Evaluator loop works best with "clear evaluation criteria"; > "Code solutions are verifiable through automated tests"; > "human review remains crucial for ensuring solutions align with broader system requirements."

### Multi-agent research system (https://www.anthropic.com/engineering/multi-agent-research-system)
Setup: > "Claude Opus 4 as the lead agent and Claude Sonnet 4 subagents" > outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval
> multi-agent systems use about 15x more tokens than chats; token usage by itself explains 80% of the variance (BrowseComp)
> upgrading to Claude Sonnet 4 is a larger performance gain than doubling the token budget on Claude Sonnet 3.7
> multi-agent systems require tasks where the value of the task is high enough to pay for the increased performance
Poor fit: shared-context domains, and "most coding tasks involve fewer truly parallelizable tasks than research". The post gives no per-role cost/accuracy split.

### Claude Code subagents (https://code.claude.com/docs/en/sub-agents)
> `model` ... `sonnet`, `opus`, `haiku`, `fable`, a full model ID such as `claude-opus-5-5`, or `inherit`. When you omit it, Claude Code picks the model in the subagent model order
Order: 1) per-invocation `model` parameter, 2) definition frontmatter, 3) `CLAUDE_CODE_SUBAGENT_MODEL`, 4) main conversation's model. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` forces one model on all subagents (v2.1.257+).
Cost advice (one line): > "Control costs by routing tasks to faster, lower-cost models like Haiku."
The page gives no criteria for choosing Haiku vs Sonnet vs inherit.

### bundled claude-api skill (Anthropic-authored; <bundled-skills>/claude-api/shared/)
cost-optimization.md:
> API spend is optimized in units of cost per completed task, not cost per token. ... a cheaper model that fails still bills its tokens, then the retry, then whatever the failure costs downstream.
> Price candidates in cost per completed task on your own traffic, including the larger model at reduced effort - per-token price lists do not predict the ranking. ... At the other end, the smallest model answered knowledge questions at a fraction of the cost per question of that same model one tier below the frontier, with markedly lower accuracy - it fits high-volume work with checkable outputs, not long agentic loops.
> Price the tail, not the median. ... the bill is decided by the tasks the cheap model fails
> The stepping-down method: sweep effort on the current model first; if `low` passes the eval, drop one model tier ... One notch at a time, against the eval
> Never keep or revert on a one-case swing. ... The published bar - around fifty cases and at least five trials per configuration - is the standard for the production cutover
> Judgment per output: whichever is cheapest for the workload - golden answers to diff against, a short rubric ..., or an automated checker (tests pass, JSON validates, required fields present).
> Switch between conversations, not inside one: a mid-conversation switch cold-starts the cache
> One self-contained step with bulky intermediates | Subagent, optionally on a cheaper model | The deciding model needs that intermediate context to judge well
managed-agents-multiagent.md: > Delegated research work is mostly searching, reading, and extracting: many input tokens, little hard reasoning. Create a second agent on a smaller current-generation model (Claude Haiku 4.5, or Claude Sonnet 5.5 when the worker needs more judgment) ... The large model spends its tokens on planning, checking, and synthesis; the small model does the bulk reading. Also shows "a fast document extractor ... a verifier that checks each file against its source, and a lead that applies the corrections".

### Haiku 5.5 prompting guide (https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5), Anthropic's own failure list
> At `low` and `medium` effort, Claude Haiku 5.5 sometimes reports a code change as done without running a check.
> With a long coding-agent system prompt at `low` effort, it sometimes stops early and hands the task back to the user. ... moving from `low` to `medium` effort roughly halved early stopping. It also more than doubled the output tokens for each attempt.
> Claude Haiku 5.5 sometimes writes reasoning-like text in the reply that users see. This happens more often with thinking off or at `low` effort.
Also: with thinking off + JSON output it "might skip a tool call it needs"; it "sometimes needs an extra nudge to search"; safety classifiers can return `stop_reason: "refusal"` with no server-side fallback.

## 5. Does Claude / Claude Code route to smaller models automatically?
(https://code.claude.com/docs/en/model-config and sub-agents; fetched excerpts)
- `opusplan`: > "uses `opus` during plan mode, then switches to `sonnet` for execution". The only automatic larger-to-smaller move described, keyed on mode, not on task difficulty.
- Default model: > "Pro, Max, Team, Enterprise, and Anthropic API: defaults to Opus 5.5" (same for Bedrock/Google Cloud/AWS platform; Foundry Sonnet 4.5).
- Explore subagent: the sub-agents page says the built-in Explore uses "the main conversation's model" (with a Fable-specific rule that resolves to the Opus alias on API/gateway connections). It does NOT say Explore defaults to Haiku; it tells you to define your own `Explore` with `model: haiku`. Built-ins listed on Haiku: `claude-code-guide`; on Sonnet: `statusline-setup`. (This contradicts the older folk belief that Explore is Haiku; page version is today's.)
- `ANTHROPIC_SMALL_FAST_MODEL`: not mentioned on the fetched model-config page (the fetch was possibly truncated). `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU,FABLE}_MODEL` "control what the aliases resolve to". I found no Anthropic text saying what background tasks use Haiku. Unverified; check the env-vars page if needed.
- Fallback chains (`--fallback-model`) and safety-classifier fallback exist but are availability/safety features, not cost routing.

## What Anthropic says
1. Pick by cost per completed task on your own eval, not per-token price; failures make the cheap model dear.
2. Tune effort on one model before adding a tier or a second model; most workloads end there.
3. Haiku 5.5 first for high-volume, latency-sensitive work whose outputs you can check (classification, extraction, routing, summaries, compaction, subagents); Sonnet 5.5 for everyday coding/agentic work; Opus 5.5 as default start for agent workloads and the hardest, open-ended, sustained-judgment work.
4. Checkable outcome + a real failure signal permits a cheap-first, escalate-on-failure policy (shown across effort levels, not tiers).
5. Delegation to cheaper workers pays only for bulk/context-overflow/long-tail work; for a dependent chain the coordinator alone at lower effort won every measured case.
6. Advisor only helps if the executor actually consults; gate the consult on a cheap signal.
7. Haiku 5.5 is weaker on factual hallucination and false-completion claims than Sonnet/Opus 5.5 (system card), and tends to skip checks / stop early at low/medium effort.

## What Anthropic does NOT say
- No published rule "send task type X to Haiku" beyond the narrowly-scoped/checkable/high-volume framing; no threshold on task difficulty or accuracy.
- No tokens/sec or latency numbers for any 5.5 model; only relative labels (Fastest/Fast/Moderate/Slower) and customer anecdotes.
- No head-to-head hallucination rate for Haiku 5.5 vs Opus 5.5 in text form; only "hallucinated more than other recent models" and AA-Omniscience net 0.12 (Haiku) / 0.35 (Sonnet); Opus 5.5's number is in a chart I could not read as text.
- No tier cascade experiment (Haiku -> Sonnet -> Opus on failure) in the docs or cookbook text I saw; the escalation evidence is across effort levels and the advisor pattern.
- No claim that Claude Code auto-routes by task difficulty; no statement about ANTHROPIC_SMALL_FAST_MODEL found.
- Nothing about an enterprise gateway, LiteLLM/Bedrock behaviour, or whether advisor/effort-per-message betas pass through it.
- Cookbook "haiku" rows are not labelled as 5.5; do not cite them as Haiku 5.5 measurements.
