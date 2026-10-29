# Literature: routing/cascading, small-model hallucination, and "checkability" — 2026-10-20

Hypothesis under test: *it is not whether a task is simple, it is whether a wrong answer can be
checked, because small models hallucinate/confabulate more.*

Evidence tiers (per `docs/research/2026-09-09-prior-art/SOURCES.md` convention):
- **FULL** = numbers read from the paper text this session (PDF to text).
- **ABS** = arXiv abstract retrieved this session via the arXiv API; only abstract claims are quoted.
- **WEB** = a live web page read this session.
- **UNVERIFIED** = from memory or not retrieved; do not cite without fetching.
Already in the repo ledger (abstract-verified there): RouterBench 2403.12031, RouteLLM 2406.18665,
FrugalGPT 2305.05176, Early Abstention 2502.09054, SWE-bench-grading papers. Extended here, not duplicated.

## A. Cascades and routers (what gates escalation, what it saves)

| Paper | Gate signal | Reported result | Tier | Bears on hypothesis |
|---|---|---|---|---|
| FrugalGPT, 2305.05176 (Chen, Zaharia, Zou, 2023) | learned scorer on the answer (cascade) | match GPT-4 with up to 98% cost reduction, or +4% accuracy at equal cost | ABS | Orthogonal-to-supports: the gate is an answer-quality scorer, i.e. a checker, not a task-simplicity label. The 98% is the paper's best case, not typical. |
| AutoMix, 2310.12963 (NeurIPS 2024) | few-shot self-verification by the small model, POMDP router because self-verification is noisy | over 50% compute reduction at comparable performance, 5 models x 5 datasets | ABS | Supports (weakly): escalation keys on "approximate correctness of outputs", not on query difficulty; authors state the self-check is noisy. Per-dataset numbers not read. |
| Mixture-of-Thought cascade, 2310.03094 (Yue et al., ICLR 2024) | answer consistency of the weak LLM across samples and CoT/PoT | matches GPT-4 at 40% of its cost (GPT-3.5-turbo weak, six reasoning sets) | ABS | Supports: gate is agreement among the small model's own samples (a cheap internal checker). Works on tasks with a canonical answer to compare. |
| Hybrid LLM, 2404.14618 (Ding et al., ICLR 2024) | router predicts query difficulty vs a tunable quality target | up to 40% fewer large-model calls with no quality drop | ABS | Contradicts-in-spirit: gates on predicted *difficulty* of the query, not on checkability. Does not test the alternative, so it cannot refute it. |
| RouteLLM, 2406.18665 | router trained on preference data, before any answer exists | over 2x cost cut without quality loss in some cases. FULL: MT-Bench, cost at 50% performance-gap recovery falls from 49% random to 13.4% of GPT-4 calls (matrix factorisation, arena + judge-augmented data); 80% PGR needs 31-37% of calls with augmented data (Table 1) | ABS+FULL | Orthogonal: preference quality on open-ended chat; no ground truth exists, so it measures what raters like, which says nothing about verifiability. |
| LM Cascades, token-level uncertainty, 2404.10136 (Gupta et al., ICLR 2024) | deferral on token-level uncertainty, learned post-hoc rule | learned rule beats naive sequence-probability aggregation; FLAN-T5 only; no headline figure in the abstract | ABS | Supports: confidence is a usable gate but raw sequence uncertainty is length-biased. Model-internal confidence, not external checking. |
| Early Abstention cascades, 2502.09054 (Zellinger et al.) | earlier stages may abstain | across six benchmarks: test loss -2.2%, cost -13.0%, error -5.0%, at +4.1% abstention | ABS | Supports mildly: abstention (a "can't check this") is worth having at the small stage; the gains are modest. |
| MixLLM, 2502.18482 | contextual bandit, predicted quality and cost per query | 97.25% of GPT-4 quality at 24.18% of cost under a time constraint | ABS | Orthogonal: predicts quality from the query; no verifier. |
| Online Cascade Learning, 2402.04513 (Nie et al.) | learned deferral; small models imitate LLM labels over a stream | parallels LLM accuracy, inference cost down by up to 90%, four benchmarks | ABS | Orthogonal: classification streams where the LLM label is the (assumed) truth. |
| RouterBench, 2403.12031 | benchmark of 405k+ outcomes | no headline saving in the abstract | ABS | Orthogonal; supplies per-model outcomes. In-repo ledger already notes the framing. |
| Martian / NotDiamond routers | proprietary | none | UNVERIFIED (no paper read; RouterBench repo is under withmartian) | Do not cite numbers. |

Reading across A: the published escalation gates split into (1) query-side predictors of difficulty or preference
(Hybrid LLM, RouteLLM, MixLLM) and (2) answer-side checks (FrugalGPT scorer, AutoMix self-verification, MoT
consistency, token uncertainty). Group 2 is checkability in a weak sense; none tests it against group 1 head to head.
None of these papers manipulates *whether the answer can be externally verified*. Savings (40-98%) are best-case, on
benchmarks with a clean reference answer.

## B. Hallucination vs scale

- **SimpleQA, 2411.04368 (OpenAI, 2024) FULL.** Table 3, percent: GPT-4o-mini correct 8.6 / not attempted 0.9 / incorrect 90.5;
  GPT-4o 38.2 / 1.0 / 60.8; Claude-3-haiku 5.1 / 75.3 / 19.6; Claude-3.5-sonnet 28.9 / 35.0 / 36.1; o1-mini 8.1 / 28.5 / 63.4;
  o1-preview 42.7 / 9.2 / 48.1. Authors: larger models are more calibrated (GPT-4o over mini, o1-preview over o1-mini) but
  every model overstates confidence. **Verdict: partial support** — the small GPT models almost never abstain, so their
  *incorrect* count is 90.5% of all questions, but the small Claude (haiku) abstains on 75% and has the lowest incorrect rate in the table
  (19.6%). Abstention behaviour is a training choice, not a size law. Within a family, bigger = better calibrated holds in both families shown.
- **AA-Omniscience, 2511.13029 (Artificial Analysis, Nov 2025) FULL.** Hallucination rate = incorrect / (incorrect + partial + abstain), i.e. share of
  non-correct answers that were attempts. Grok 4 and GPT-5 (high) top accuracy at 39% with hallucination rates 64% and 81%; Claude 4.1 Opus
  36% accuracy, one of the lowest rates, Index 4.8 (only three models above 0). Claude 4.5 Haiku: 16% accuracy, 26% hallucination rate, "more reliable
  than similarly accurate" gpt-oss-120b (high). Section 3.4: size is positively associated with *accuracy* but "larger models do not consistently exhibit lower hallucination rates";
  Nemotron Nano 9B V2 beats larger peers on the Index. **Verdict: contradicts the size half of the hypothesis** — hallucination rate (the rate at which a non-knowing model
  guesses) is not monotone in size; it tracks training for abstention. Small models know less (accuracy) but are not necessarily worse at saying so.
- **Vectara hallucination leaderboard (github.com/vectara/hallucination-leaderboard) WEB, page dated "last updated 2026-10-16", HHEM-2.3.** Summarisation faithfulness. Best finix_s1_32b 1.8%;
  worst ministral-3-3b-2512 24.2%, Phi-4-mini-instruct 23.5%; but gpt-5.4-nano 3.1% and gemini-2.5-flash-lite 3.3%. Within families the smaller sibling is slightly worse
  (qwen3-4b 5.7% vs qwen3-32b 5.9% is an inversion in the wrong direction by 0.2 points; ministral 3B 7.3% vs 8B 7.4% likewise essentially tied). **Verdict: weak/orthogonal.**
  Grounded summarisation is the checkable-against-source case, and small modern models do well on it; the worst are specific small models, not small models as a class. Page lists no parameter counts, so size was inferred from names.
- **TruthfulQA, 2109.07958 (Lin et al., ACL 2022) ABS.** "The largest models were generally the least truthful" (GPT-3, GPT-Neo/J, GPT-2, T5; best 58% vs human 94%). **Contradicts** a "small = more hallucination" law for imitative falsehoods; this is the 2021 inverse-scaling result and is about misconceptions, on models long superseded.
- **Kadavath et al., "Language Models (Mostly) Know What They Know", 2207.05221 (2022) FULL/ABS.** Calibration "improves with model size" and with few-shot; larger models are better at self-evaluating P(True). **Supports** that smaller models are less calibrated and worse self-checkers (same-family, pre-RLHF-era models). P(IK) generalises only partly across tasks.
- **Kalai et al., "Why Language Models Hallucinate", 2509.04664 (2025) FULL/ABS.** Theory: hallucinations are binary-classification errors (cannot tell a wrong statement from a fact) and persist because benchmarks reward guessing over abstaining. Pretrained models are calibrated; RL post-training makes them worse (GPT-4 calibration histograms, Fig. 2). Introduces the "singleton rate" bound (fraction of facts seen exactly once in training). **Bears:** supports a *knowledge-coverage* story (small models see fewer facts, so more arbitrary-fact errors) but states no scale experiment; the paper's remedy is scoring that rewards abstention, which is exactly an abstention-vs-guess lever, not a size lever. Orthogonal-to-supports.

**What B establishes:** small models know less (accuracy rises with size, FULL for SimpleQA and AA-Omniscience). Whether they *confabulate more per non-knowledge* depends on abstention training, and the best cross-model data (AA) shows it is not monotone in size. Calibration does improve with size within family (Kadavath, SimpleQA).

## C. Generation-verification gap

- **Large Language Monkeys, 2407.21787 (Brown et al., 2024) FULL (PDF read).** Repeated sampling, coverage = fraction solved by any sample.
  - SWE-bench Lite, DeepSeek-Coder-V2-Instruct: 15.9% with 1 sample to 56% with 250 samples (coverage), above the 43% single-sample SOTA (GPT-4o + Claude 3.5 Sonnet mix). Coverage here is selected by the benchmark's tests.
  - Cost (Table 1, Moatless Tools agent): DeepSeek x5 attempts 29.62% solved at $10.8 total (1x); GPT-4o x1 24.00% at $39 (3.6x); Claude 3.5 Sonnet x1 26.70% at $51 (4.7x). Per attempt $0.0072 vs $0.13 vs $0.17.
  - FLOP-matched: on MATH, GSM8K, MiniF2F Llama-3-8B has higher coverage than 70B at equal FLOPs; on CodeContests 70B is "almost always more cost effective". So the small-model win is task dependent even with a perfect verifier.
  - **No verifier case (the key one):** MATH with Llama-3-8B-Instruct, coverage rises 82.9% (100 samples) to 98.44% (10,000), but majority vote or reward-model selection moves only 40.50% to 41.41%. Verifier methods "plateau around 100 samples" (ArmoRM-Llama3-8B reward model, majority vote, RM+vote). Authors: increasingly rare correct samples help "only if verifiers can find the needle in the haystack".
  - **Imperfect verifiers cost:** 11.3% of SWE-bench Lite problems have flaky tests; 35 of 122 CodeContests problems with Python3 reference solutions have "correct" solutions failing the tests (false negatives).
  - **Verdict: strongest direct support** for checkability as the gate: a weak model plus an automatic verifier beats a strong single sample (and is 3.6-4.7x cheaper in SWE-bench Lite); with only majority vote or a reward model the same weak model is stuck at ~41% against ~98% coverage. Caveats: coverage is oracle-selected; the 56% figure counts any sample passing tests, and its false-positive rate is not measured in this paper; the cost comparison is against 2024 models; the dollar comparison is one agent framework.
- **CodeT, 2207.10397 (Chen et al., ICLR 2023) ABS.** Model-generated tests plus dual execution agreement select among samples: HumanEval pass@1 to 65.8%, +18.8 absolute over code-davinci-002 and >20 over previous SOTA. **Supports:** cheap executable checking recovers accuracy; the checker is itself model-generated, so it is imperfect.
- **AlphaCode, 2203.07814 (Li et al., 2022) ABS.** Average rank top 54.3% on Codeforces contests with >5,000 participants; large-scale sampling followed by filtering on program behaviour is one of three critical components. **Supports** (same mechanism; exact filtering ratios not read).
- **Mind the Gap, 2412.02674 (Song et al., ICLR 2025) FULL/ABS.** Generation-verification gap (GV-Gap) of self-verification; the relative gap scales monotonically with pre-training FLOPs for good verification methods (CoT-score). "Small models cannot self-improve": for Qwen-1.5 0.5B, Qwen-2 0.5B and Llama-2 7B the gap is non-positive for nearly all verifiers although generation accuracy is non-trivial. In cross-verification the gap grows with verifier capability and shrinks with generator capability; most models fail to self-improve on tasks beyond their own reasoning. **Verdict: refines** the hypothesis — checkability is not free: small models are poor *self*-verifiers, so the checker must be external (tests) or a stronger model.
- **Huang et al., "LLMs Cannot Self-Correct Reasoning Yet", 2310.01798 (ICLR 2024) FULL.** With oracle labels deciding when to stop, self-correction helps (GPT-3.5 GSM8K 75.9 to 84.3; CommonSenseQA 75.8 to 89.7; HotpotQA 26.0 to 29.0; GPT-4 HotpotQA 49 to 59). Intrinsic self-correction without the oracle hurts: GPT-3.5 CommonSenseQA 75.8 to 38.1 after one round, GPT-4 GSM8K 95.5 to 91.5 (round 1) and 89.0 (round 2). Authors: the gains vanish when oracle labels are absent. **Supports strongly** that external ground truth, not the model's opinion of itself, is what makes a retry productive. Tested on GPT-3.5/GPT-4/GPT-4-Turbo/Llama-2-70B only.
- **LLM Evaluators Favor Their Own Generations, 2404.13076 (Panickssery et al.) ABS.** Self-preference bias rises linearly with self-recognition ability (GPT-4, Llama 2). **Supports** the need for a non-self checker; no routing numbers.
- **Generative AI Paradox, 2311.00059 (West et al., ICLR 2024) ABS.** Models can beat humans at generation while falling short on understanding, with weak correlation between the two. **Contradicts** the folk "verification is easier than generation" for models themselves: for LLMs understanding/discrimination can lag generation. Reconciles with C above only if the verifier is mechanical, not another LLM.
- **Weak-to-strong, 2312.09390 (Burns et al., 2023) ABS.** Strong models finetuned on weak labels beat their weak supervisors; GPT-4 with a GPT-2-level supervisor plus auxiliary confidence loss recovers close to GPT-3.5-level. **Orthogonal:** training-time supervision, not routing. Shows weak signals can be exploited but "far from recovering full capabilities".
- **Snell et al., 2408.03314 (2024) ABS.** Test-time compute with a process-reward verifier: where a smaller base model has "somewhat non-trivial" success, test-time compute can beat a 14x larger model in FLOPs-matched evaluation; 4x efficiency over best-of-N. Effect depends on prompt difficulty. **Supports** with a learned verifier, and marks the limit: needs non-trivial base success.

## D. Agent-level evidence

- SWE-bench, 2310.06770 ABS: original best model Claude 2 solved 1.96%; historical only.
- Large Monkeys SWE-bench Lite table (above) is the only small-vs-large agent cost comparison verified here.
- Small LLMs Are Weak Tool Learners, 2401.07324 ABS: decomposing planner/caller/summarizer into separate fine-tuned smaller LLMs beats a single-LLM approach on tool-use benchmarks; abstract gives no figures. Supports the narrower claim that small models need the task cut into checkable pieces; magnitude UNVERIFIED.
- Wang et al. 2503.15223 and UTBoost 2506.09289 (already in the repo ledger): hidden tests accept wrong patches (7.8% of passing patches fail developer suite; resolution inflated 6.2 points). **Qualifies** the verifier argument: a checker with false positives lets confabulation through, so "checkable" means "checkable by a sound check".
- **Not found / UNVERIFIED:** orchestrator-worker cost studies and a paper titled "When to use small LLMs as subagents". No source retrieved; do not cite.

## E. Synthesis

**Established (read in the papers):**
1. A cheap model plus an automatic verifier can match or beat a stronger single sample at lower cost (Large Monkeys: 56% vs 43% on SWE-bench Lite coverage; $10.8 vs $39-51 for 24-30% solved; CodeT +18.8 points; AlphaCode filtering).
2. Remove the automatic verifier and the benefit collapses: 98.44% coverage but 41.41% selected on MATH with Llama-3-8B; majority vote and an 8B reward model plateau near 100 samples.
3. Models cannot reliably self-check without ground truth: intrinsic self-correction lowers accuracy (GPT-3.5 CommonSenseQA 75.8 to 38.1), and small models have non-positive self-verification gap (Song et al.). Verification must come from outside the generating model.
4. Larger models know more (SimpleQA, AA-Omniscience accuracy rise with size) and are better calibrated within a family (Kadavath; SimpleQA GPT-4o vs mini, o1-preview vs mini).
5. Routers and cascades report 40-98% cost savings at matched quality, but only on benchmarks with a reference answer or preference proxy; savings are gated either by a query-difficulty predictor or an answer-side score. No published router was tested against the checkability variable directly.

**Against or complicating the hypothesis:**
- "Small models hallucinate more" is not a size law. AA-Omniscience reports hallucination rate is not monotone in size and Haiku 4.5 (16% accuracy, 26% rate) beats gpt-oss-120b; SimpleQA shows Claude-3-haiku with the lowest incorrect share (19.6%) while GPT-4o-mini is at 90.5%. Abstention is trained behaviour (Kalai: benchmarks reward guessing). TruthfulQA found larger = less truthful for imitative falsehoods. The accurate form is "smaller models know less, so a given task exposes more unknowns", and whether they bluff is model-specific.
- On Vectara, modern small models (gpt-5.4-nano 3.1%, gemini-2.5-flash-lite 3.3%) are near the top; same-family size effects are 0.1-0.2 points.
- A perfect verifier is rarely available: flaky tests (11.3% of SWE-bench Lite), test-suite false negatives (35 of 122 CodeContests problems), and false positives (7.8%) all cap the gain. "Checkable" must mean sound-checkable.
- The sample/verify route is not a routing decision made per task up front; it spends 5-250x more small-model calls. It is cheaper only when per-sample cost is >10x lower (Large Monkeys' own caveat) and on CodeContests the 70B beat 8B per FLOP even with a perfect verifier.

**Folklore (stated widely, not supported by anything read here):**
- "Verification is easier than generation" as a property of LLMs: the Generative AI Paradox and Song et al. show it holds for mechanical checkers and strong cross-verifiers, not for a model grading itself.
- "Router savings of 50-98%" as general expectation: best-case, benchmark-specific.
- Any claim about Martian/NotDiamond performance, and any orchestrator-worker or "small subagent" cost law: nothing retrieved.
- That task simplicity is the wrong axis outright: Hybrid LLM and RouteLLM route on predicted difficulty with real savings; the literature has not run the experiment that separates difficulty from checkability. Our hypothesis is plausible and consistent with items 1-3, but untested as a causal claim. Best design implication: a delegate gate should ask for an external, sound check (tests, schema, source-grounded comparison), and treat the small model's self-report as noise.

## Gaps to close if this becomes load-bearing
Fetch full text for AutoMix, Hybrid LLM, FrugalGPT, MoT cascade (only abstracts read); read Huang-style self-correction replications on small open models; read AA-Omniscience Figure 9/10 values per model size; look for a head-to-head of checkable vs uncheckable tasks in a router.
