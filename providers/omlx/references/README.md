# `references/` — published-benchmark reference corpus

Four JSON files holding what *other people* have published about model quality, so this
project's own measurements can be sited against a public backdrop. **None of these files
contains a measurement made by this project**, and none of them is a substitute for one.

Every file carries a top-level `_source`, `_retrieved`, a description of what kind of
evidence it is, and a `models` map keyed by the vendor's own model name. The three files
added on 2026-09-29 name that description `_basis`; `artificial-analysis.json` predates
that convention and calls it `_basis_note`. A value equal to the string `"NOT_OBTAINED"`
means the source does not publish it — never that the value is zero, and never a
remembered or estimated figure. Read that field before using a number from the file.

## The four files

| File | Models | What it actually measures | Good for | Do not use it for |
|---|---:|---|---|---|
| `artificial-analysis.json` | 259 | AA Intelligence Index v4.3.2 plus per-eval fields (GPQA, HLE, SciCode, MMMU-Pro, AA-LCR, AA-Omniscience incl. a hallucination rate), with params, license, context and price | The only file with **parameter counts**, so it is what turns "≤200B" into a filter the other files can borrow; also the only one pairing capability with price | Ranking, unless you first check `intelligenceIndexIsEstimated` — 491 of AA's 679 records are estimates |
| `lmarena.json` | 409 | Human-preference Elo from ~8.5M pairwise votes: **overall** and the **Instruction Following** category, each with rank, score, published ±CI, rank spread and vote count | Whether humans *prefer* a model's replies, and how wide the uncertainty is — the ±CI is published, so overlapping intervals are visible | A capability or correctness claim. It is preference, not grading. The IF category is a vote slice, **not** a rubric benchmark like IFEval/IFBench |
| `vectara-hhem.json` | 108 | HHEM-2.3 hallucination rate **and** answer rate on grounded summarization of short documents. **Lower hallucination rate is better** | The only *independent, single-harness, same-task* factuality axis in the corpus — every model scored the same way by the same judge | Factuality in general. It is grounded summarization only, the judge is itself a model, and a low rate at a low answer rate is abstention (arctic-instruct: 4.3% at a 62.7% answer rate) |
| `vendor-cards.json` | 10 | IFBench / IFEval / MultiChallenge / MMLU-Pro / RULER / AA-LCR / AA-Omniscience as stated on HuggingFace model cards, for models with an MLX quant | The only file with **instruction-following rubric scores**, and the only one that records two vendors disagreeing about the same model | Anything requiring comparability. 31 of 80 cells are filled, and no card states a CI or run count for any of them |

## Three hard limits — they apply to conclusions, not just to cells

**1. Most of `artificial-analysis.json` is estimated, and AA says so itself.**
`intelligenceIndexIsEstimated` is AA's own flag, true on 491 of its 679 records. An
estimated score is not a measurement: it must not be plotted, ranked, or differenced as
one. This is the largest file in the corpus and the one most likely to be reached for
casually, which is exactly why the flag has to be checked every time.

**2. Nothing anywhere in this corpus measures quantisation, and the local fleet is
quantised.** AA publishes no precision field (zero matches for `fp8|fp4|int4|awq|bf16|…`
across all 679 records). LMArena publishes none. Vectara publishes none. Of the ten vendor
cards, exactly one — `openai/gpt-oss-120b` — states the precision its own evals ran at
(MXFP4). Every other number here describes whatever precision some host served,
unlabelled, while the MLX quants this project can actually run are 2–8 bit. **A published
score does not transfer to a 4-bit local run**, and no file here can tell you what the gap
is. That gap is the thing this project measures; the corpus is the backdrop, not the answer.

**3. `vendor-cards.json` is self-reporting end to end, and the bias is not directional.**
All 43 readings are vendor-reported; 27 are self-reports. Each carries `reported_by`,
`is_self_report`, the verbatim `as_labelled_on_card` string, and
`compared_against_in_that_table` — the vendor's chosen comparison set, which is where the
flattery lives (Gemma 4's table compares only against other Gemmas). The naive correction
"discount the self-report" **does not work**, because the observed disagreements run both
ways:

- `gpt-oss-120b` MultiChallenge: Qwen says **45.3**, NVIDIA says **58.29** — 12.99 points
  apart on the same benchmark for the same model, wider than most gaps this corpus would be
  used to rank.
- `Qwen3.5-122B-A10B` IFBench: three readings spanning 4.18 points, highest is the self-report.
- Nemotron 3 Super versus **itself**: NVIDIA's two cards state different MMLU-Pro, IFBench
  and AA-LCR figures for the same model, same month.
- Gemma 4 26B A4B MMLU-Pro: Google **82.6**, NVIDIA **85.20** — the *competitor* reports
  the higher number.

Also: "IFBench" is at least three incompatible variants on these cards — unlabelled,
`(prompt)`, and `(loose)`. Two IFBench numbers from two cards are not necessarily the same
measurement.

## Joining the files

There is **no shared key**. Each source names models its own way
(`claude-opus-5.5-high`, `google/gemma-4-31b-it`, `Qwen/Qwen3.5-122B-A10B`,
`Qwen3.8 27B (xhigh)`), and no join table exists here. Match by hand and record the match,
because a fuzzy name match across two of these files is a fabrication risk, not a
convenience — the one case where a match was uncertain is flagged in
`vendor-cards.json` under `_caution_nemotron_naming` rather than silently merged.

---

## ⚠️ Verification status — read before quoting

`lmarena.json`, `vectara-hhem.json` and `vendor-cards.json` were retrieved on
2026-09-29 by an agent that **died on an API error partway through its own
verification pass**. Its last report said the 34 discrepancies it had found were an
artifact of its checker's number formatting (`100.0` rendered as `100`) rather than
wrong data — but it did not finish proving that.

So: the files load, the units and shapes are tested
(`evals/harness/tests/test_refer.py`, the multi-source section), and `bin/refer`
consumes them. **Their per-row fidelity against the source pages is NOT fully
verified.** Before a number from these three files becomes load-bearing, re-check it
against the URL in its own `_source` field. `artificial-analysis.json` is not
affected — it was parsed from the site's own embedded JSON payload and spot-checked.

Known cross-source hazard, already handled in code: the three sources do not agree on
model naming (`Gemma 4 31B (Non-reasoning)` / `gemma-4-31b` / `google/gemma-4-31b-it`).
`refer.Corpus._record` joins on a normalised key and **refuses a near-miss or an
ambiguous match** rather than picking the closest — a wrong join would attribute one
model's hallucination rate to another.
