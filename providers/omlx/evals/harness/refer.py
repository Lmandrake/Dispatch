"""Delegation tiers from PUBLISHED benchmarks instead of our own sweeps.

WHY THIS REPLACES THE SWEEP PATH. Our eight fixtures cannot separate models: six of
the eight are passed at 1.00 by anything competent, and no trial count fixes that
because `var_int/n_tasks` carries no `n_reps` term. An outside ruler made it
undeniable -- Artificial Analysis spreads the same nine models 43 index points while
our index ties them (`charts/05-local-vs-anthropic.html` panel 5). So the instrument
moves outward: cite benchmarks that are not saturated in our band, and spend no more
model calls of our own.

WHAT THIS IS. A rule-based lookup, not a trained router. Per (model, job kind) it
reads published per-skill scores, applies a literature-cited haircut when we serve a
quantised copy, and returns one of the existing tiers -- DELEGATE / VERIFY / DO_NOT /
UNKNOWN -- with the provenance of every number that fed it.

WHY NOT A TRAINED ROUTER. In the band we can actually run (open weights <=35B) only
13 models have a measured AA index *and* IFBench *and* a hallucination rate, and 491
of AA's 679 records are AA's own estimates. Fitting on 13 partly-estimated rows would
produce a clean, plausible, unfounded number -- the failure this repo keeps catching.
Prior art was read for structure and deliberately not copied: RouteLLM
(arXiv:2406.18665) routes per query on preference data; FrugalGPT (2305.05176) and
`Cost-Saving LLM Cascades with Early Abstention` (2502.09054) cascade on cost;
RouterBench (2403.12031) and LLMRouterBench (2601.05903) benchmark routers. All
optimise cost-vs-quality on general chat. Our question is different and asymmetric:
*will this model quietly get it wrong*, which is why Faithfulness is a gate here
rather than a term in a sum.

TWO THINGS IT REFUSES TO DO
  * Average away a weakness. A job's score is the MINIMUM over its required skills.
    A model that follows instructions beautifully and fabricates is not
    two-thirds-good at attribution; it is unusable for it.
  * Guess when it does not know. A missing metric for a required skill returns
    UNKNOWN, never a midpoint. `0` must mean measured zero -- the same rule the atom
    scoring already lives by.

AND ONE JUDGEMENT IT MAKES OPENLY. Ranking is by percentile within the reference
corpus, which needs no invented number -- but a percentile alone was not safe, because
the corpus has a long weak tail and "97th percentile" can mean "better than a lot of
junk". So `DELEGATE_FLOOR` adds an ABSOLUTE bar per metric, and those numbers ARE
chosen by judgement. Each records the distribution it was read off so it can be
argued with, and both gates must pass for DELEGATE. An earlier version of this
docstring claimed the module invents no thresholds; that was true then and false
once the floors landed, which is exactly the kind of drift this repo keeps catching
in its own prose.

WHAT IT IS HONEST ABOUT. Most inputs are AA estimates or vendor self-reports, about
full-precision models we do not run. Nothing reaches DELEGATE on an estimated or
assumed input -- see `_tier`. Treat every verdict as a prior to be revised once the
thing has actually been used, which is the point of shipping it.

READS PUBLISHED FIGURES ONLY -- NO ARCHIVE CROSS-CHECK. An earlier version of this
module also consulted our own archived sweep's routing table and downgraded a
DELEGATE verdict to VERIFY when the two disagreed. The project
ruling (2026-10-01) is to use published figures only and keep old scores archived.
`assess()` now consults nothing but the reference corpus under `references/`;
it has no `archived`/`conflict`/`conflict_kind` keys, and a model that is
`measured`, unhaircut, and clears both the percentile band and `DELEGATE_FLOOR` can
reach DELEGATE even where the retired cross-check used to cap it at VERIFY. That is
the intended effect of the ruling, not a regression.
"""

from __future__ import annotations

import json
import pathlib

# Reuse the router's vocabulary verbatim so downstream semantics do not fork.
from evals.harness.router import DELEGATE, DO_NOT, UNKNOWN, VERIFY

REFERENCES = pathlib.Path(__file__).resolve().parents[2] / "references"

# --------------------------------------------------------------------- skills --
#: Adopted from Artificial Analysis's own "By Skill" tagging rather than invented,
#: so our axes line up with the axes the published numbers are organised along.
SKILLS = ("instruction_following", "faithfulness", "long_context", "reasoning",
          "coding", "tool_use", "knowledge")

#: metric id -> where it lives and how to read it.
#:   file    : which references/*.json
#:   field   : key inside that record
#:   higher_is_better: direction. Hallucination RATE is inverted.
#:   note    : what the number actually measures, because two sources can both be
#:             "hallucination" on wildly different difficulty and must not be pooled.
METRICS = {
    "aa_ifbench": {
        "file": "artificial-analysis.json", "field": "ifbench",
        "higher_is_better": True, "skill": "instruction_following",
        "note": "IFBench via AA. 294 of allenai's 300 verifiable-constraint prompts, "
                "loose mode. In-band open weights span ~0.27-0.71.",
    },
    "aa_halluc": {
        "file": "artificial-analysis.json", "field": "omniscienceHallucinationRate",
        "higher_is_better": False, "skill": "faithfulness",
        "note": "AA-Omniscience hallucination rate over 6,000 hard questions. Runs "
                "0.49-0.97 in our band -- a HARD test, not comparable to Vectara's.",
    },
    "aa_lcr": {
        "file": "artificial-analysis.json", "field": "lcr",
        "higher_is_better": True, "skill": "long_context",
        "note": "AA Long Context Reasoning, 100 long documents, carries a "
                "faithfulness dimension.",
    },
    "aa_gpqa": {
        "file": "artificial-analysis.json", "field": "gpqa",
        "higher_is_better": True, "skill": "reasoning",
        "note": "GPQA Diamond.",
    },
    "aa_livecodebench": {
        "file": "artificial-analysis.json", "field": "livecodebench",
        "higher_is_better": True, "skill": "coding",
        "note": "LiveCodeBench.",
    },
    "aa_tau2": {
        "file": "artificial-analysis.json", "field": "tau2",
        "higher_is_better": True, "skill": "tool_use",
        "note": "tau2-bench, tool use in dialogue.",
    },
    "aa_omniscience_acc": {
        "file": "artificial-analysis.json", "field": "omniscienceAccuracy",
        "higher_is_better": True, "skill": "knowledge",
        "note": "AA-Omniscience factual accuracy.",
    },
    "vectara_halluc": {
        # Reported as a percentage (1.8 means 1.8%), so scaled to a fraction to sit
        # on the same axis as AA's rate. Without the scale a 14% hallucinator would
        # read as 14.0 and be compared against fractions -- off by 100x, and in the
        # direction that makes every model look catastrophic.
        "file": "vectara-hhem.json", "field": "hallucination_rate_pct",
        "scale": 0.01,
        "higher_is_better": False, "skill": "faithfulness",
        "note": "Vectara HHEM-2.3 summarisation hallucination rate, ~5-18%. A much "
                "EASIER test than AA-Omniscience; kept separate on purpose.",
    },
    "lmarena_if": {
        # Nested under a per-category object, and an Elo (~1300-1520), not a
        # proportion -- which is why its DELEGATE_FLOOR is 1400 and not 0.6.
        "file": "lmarena.json", "path": ("instruction_following", "score"),
        "higher_is_better": True, "skill": "instruction_following",
        "note": "LMArena Instruction Following category Elo. Human preference, so it "
                "measures something different from IFBench's verifiers.",
    },
}

# ----------------------------------------------------------------------- jobs --
#: Our job kinds -> the skills a model must have to be handed one.
#: `gates` are skills where weakness is disqualifying rather than discounted, which
#: is why the job score is a minimum: fabricating on an attribution task is not
#: offset by writing tidy prose.
JOBS = {
    "A2": {"label": "Pick the right files from a search dump",
           "skills": ("instruction_following",)},
    "A3": {"label": "Pull distinct error types from a log",
           "skills": ("instruction_following",)},
    "E3": {"label": "Tighten wordy text, keep the hedges",
           "skills": ("instruction_following",)},
    "E4": {"label": "Strip marketing hype, keep the facts",
           "skills": ("instruction_following", "faithfulness")},
    "F1": {"label": "Turn a brief into a slide outline",
           "skills": ("instruction_following",)},
    "F2": {"label": "Write release notes from a changelog",
           "skills": ("instruction_following",)},
    "B4": {"label": "Fix garbled names & acronyms in a transcript",
           "skills": ("long_context", "faithfulness")},
    "B5": {"label": "Pull who-owns-what action items from a meeting",
           "skills": ("faithfulness", "long_context")},
    "CODE": {"label": "Write or fix code against a spec",
             "skills": ("coding", "instruction_following")},
    "AGENT": {"label": "Drive tools to complete a multi-step task",
              "skills": ("tool_use", "instruction_following", "reasoning")},
}

# --------------------------------------------------------- quantisation haircut --
#: AA publishes NOTHING about precision -- zero matches for
#: fp8|fp4|int4|int8|4-bit|8-bit|awq|gptq|bf16|quant across all 679 records -- and we
#: serve 4-bit and 8-bit MLX quants. So every published number is an upper bound on
#: the weights we load, and the gap is taken from the literature rather than invented.
#:
#: Values are RELATIVE penalties applied to the percentile, keyed by (precision,
#: skill). Long context is penalised hardest at 4-bit because that is what the
#: measurements say, and it lands squarely on B4/B5 -- our transcript jobs.
QUANT_HAIRCUT = {
    ("8bit", "*"): (0.00, "arXiv:2505.20276 measures ~0.8% drop at 8-bit; "
                          "arXiv:2504.04823 finds W8A8/W4A16 lossless; "
                          "arXiv:2606.21257 calls 8-bit weight-only "
                          "'effectively lossless'."),
    ("4bit", "long_context"): (0.35, "arXiv:2505.20276: 4-bit causes drops of up to "
                                     "59% on >64K-token tasks; Llama-3.1-70B fell "
                                     "32% under BNB-nf4. The largest penalty here."),
    ("4bit", "faithfulness"): (0.20, "arXiv:2609.24799 finds W4 preserves accuracy "
                                     "but weakens answer-supporting evidence; "
                                     "arXiv:2602.06181 measures 4-bit showing 4-6x "
                                     "more behavioural change than 8-bit."),
    ("4bit", "*"): (0.11, "arXiv:2501.03035 (AWQ/GPTQ, Llama-3, MATH): up to 32.39% "
                          "degradation, average 11.31%. Smaller models fare worse "
                          "(arXiv:2409.11055, arXiv:2307.08072)."),
}

#: Local oMLX / remote enterprise ids -> the published model they correspond to, and at what
#: precision. `basis` records how good the correspondence is, because none of these
#: is a like-for-like: AA never tested the quant, and sometimes never tested the
#: variant at all.
#:
#: MODE CONVENTION. AA publishes a model twice, `(Reasoning)` and `(Non-reasoning)`,
#: and the gap is large -- Gemma 4 31B moves 0.53 -> 0.76 on IFBench and 0.47 -> 0.70
#: on long context. `router`/`bin/route` default to `nothink`, so every alias here
#: names the `(Non-reasoning)` row and the verdicts describe the mode we actually
#: run. This module is otherwise mode-BLIND: nothing checks that the suffix matches
#: the mode a caller passes, so routing `--mode think` gets a verdict measured on the
#: weaker row. Dropping the suffix entirely is worse than picking the wrong one -- it
#: is what hid the GLM defect below, because the bare name silently fell through to a
#: different source instead of failing.
ALIASES = {
    # --- local oMLX fleet -------------------------------------------------
    "Qwen3.8-27B-8bit": ("Qwen3.8 27B (Non-reasoning)", "8bit", "measured"),
    "Qwen3.8-27B-OBLITERATED-OptiQ-4bit": (
        "Qwen3.8 27B (Non-reasoning)", "4bit", "proxy"),
    "Qwen3.5-9B-MLX-4bit": ("Qwen3.5 9B (Non-reasoning)", "4bit", "estimated"),
    # 🔴 CORRECTED 2026-09-29. This said ("GLM-4.7-Flash", "8bit", "proxy") and
    # NO_AA_COVERAGE claimed the model was "absent from AA's current list and from
    # LMArena". Both halves were false: AA carries BOTH mode rows, and LMArena
    # carries `glm-4.7-flash` -- which this module was already reading, while its own
    # docstring said the source did not have it. The alias simply lacked AA's mode
    # suffix, so the exact-name lookup missed and the normalised one could not join
    # `glm47flash` to `glm47flashnonreasoning`. It resolved via LMArena anyway, which
    # is exactly why no guard fired: see `test_a_declared_coverage_gap_must_really_
    # be_absent`, added with this fix.
    "GLM-4.7-Flash-8bit": ("GLM-4.7-Flash (Non-reasoning)", "8bit", "estimated"),
    # Added 2026-10-01. AA MEASURED this row (`intelligenceIndexIsEstimated: false`)
    # and it carries both skills B5 needs -- `omniscienceHallucinationRate` 0.305 and
    # `lcr` 0.717 -- which corrects a handoff claim that AA published no faithfulness
    # figure for it and left B4/B5/E4 permanently UNKNOWN. They are answerable.
    #
    # 🔑 WHY `proxy` AND NOT `measured`, even though AA measured it: AA publishes this
    # model ONCE, with no `(Reasoning)`/`(Non-reasoning)` suffix, so there is no way to
    # tell which mode the number was taken in. We serve `nothink`. Claiming `measured`
    # would assert a mode correspondence nobody published, and thinking mode was
    # separately measured to HELP on these benchmarks -- so the unknown leans
    # optimistic, which is the direction that does unverified damage. `proxy` caps it
    # at VERIFY. Promote it only if AA splits the row or we measure the mode ourselves.
    "K2-Horizon-MoVA-36B-A4B-8bit": ("K2 Horizon MoVA 36B A4B", "8bit", "proxy"),
    # RETIRED 2026-10-01: `gemma-4-31b-it-8bit` and `Qwen3.6-27B-8bit` were deleted
    # from disk on 2026-09-29 (score-justified; see costmap.py's drop note), but their
    # aliases stayed, so `refer table` went on recommending two models that are not
    # here -- VERIFY 60% and 54% on B5, above everything that does exist. An alias is
    # not an inventory, and nothing in this module reads the served fleet, so a dead
    # alias is indistinguishable from a live one. Removed rather than annotated.
    # `remote-gemma-31b-128k` below is NOT part of that retirement: it is a model on a
    # remote enterprise endpoint, never on this disk.
    # --- remote enterprise model service ---------------------------------
    "remote-gemma-31b-128k": ("Gemma 4 31B (Non-reasoning)", "8bit", "estimated"),
    # remote-118b is an example of a model with no public leaderboard entry
    # under that name. Deliberately NOT
    # aliased: a guess here would be worse than UNKNOWN. It has no published evidence.
}

#: Published names an alias points at that Artificial Analysis does NOT cover, with
#: the reason. Recorded rather than silently tolerated, because the alternative is a
#: typo in ALIASES reading as "no data" forever. Anything here must get its evidence
#: from another source file (a vendor card, LMArena, Vectara) or stay UNKNOWN.
#: Currently EMPTY, and that is the corrected state. Its only entry claimed
#: GLM-4.7-Flash was unmeasured by everyone; AA carries both of its mode rows and
#: LMArena carries it too. An entry here is a claim ABOUT THE CORPUS and is now
#: tested against the corpus rather than merely read.
NO_AA_COVERAGE: dict[str, str] = {}

#: Job kinds no aliased model can be assessed for, with the reason. Same discipline as
#: NO_AA_COVERAGE: a gap that is DECLARED is distinguishable from a gap that is a bug,
#: and the declaration is itself tested against the corpus so it cannot rot.
UNCOVERED_JOBS = {
    "CODE": "`coding` rests on aa_livecodebench alone, and AA publishes no "
            "LiveCodeBench figure for ANY model we alias -- all seven return None. "
            "CODE was briefly answerable (as DO NOT) only because two models that "
            "did carry an LCB figure were installed; both were deleted 2026-09-29 "
            "for being DO NOT on all ten jobs. So UNKNOWN here is the honest answer "
            "about the fleet we own, not a defect. Closing it needs a second coding "
            "source in METRICS, not a lower bar.",
}

#: Percentile bands, kept in one place so the bar can be moved knowingly.
_DELEGATE_PCTILE = 0.70
_VERIFY_PCTILE = 0.40

#: Absolute floors on the RAW metric that DELEGATE must ALSO clear.
#:
#: WHY A PERCENTILE IS NOT ENOUGH. The reference corpus holds 259 models including
#: very small and superseded ones, so "97th percentile" can mean "better than a lot
#: of junk" rather than "good enough to hand work to". That is not hypothetical: a
#: 27B local model came out at the 97th percentile on faithfulness for the hardest
#: job in the suite, which our own archived sweep scored 0.28.
#:
#: These are a JUDGEMENT, not a measurement, and each records the distribution it was
#: read off so it can be argued with. Direction follows the metric.
DELEGATE_FLOOR = {
    "aa_ifbench": (0.60, "corpus spans 0.12-0.80; in-band open weights 0.27-0.71. "
                         "0.60 puts a model in the clearly-competent group rather "
                         "than merely above the weak tail."),
    "aa_halluc": (0.35, "corpus spans 0.009-0.985; in-band open weights 0.49-0.97, "
                        "i.e. most small models fabricate on most questions. LOWER "
                        "is better, so this is a ceiling."),
    "aa_lcr": (0.60, "corpus spans 0-0.833. Below 0.60 the model is not reliably "
                     "reasoning over a long document."),
    "vectara_halluc": (0.10, "leaderboard spans ~0.01-0.18 on an EASIER "
                             "summarisation test. LOWER is better."),
    "aa_livecodebench": (0.50, "corpus spans 0.002-0.878. Half the problems solved "
                               "is the point where a coding hand-off saves more "
                               "time than the review costs."),
    "aa_tau2": (0.50, "corpus spans 0-0.988, and the distribution is bimodal -- "
                      "models either handle tool dialogue or collapse on it, so a "
                      "mid-range bar separates the two groups."),
    "aa_gpqa": (0.60, "corpus spans 0.098-0.923. GPQA Diamond is graduate-level, so "
                      "0.60 is 'reasons reliably', not 'expert'."),
    "aa_omniscience_acc": (0.15, "corpus spans 0.001-0.27 -- a hard test where even "
                                 "frontier models sit low."),
    "lmarena_if": (1400, "Arena Elo, not a proportion. Roughly the top-100 band."),
}


def clears_floor(metric: str, raw: float) -> bool | None:
    """Does this raw value clear the absolute floor? None when no floor is declared."""
    if metric not in DELEGATE_FLOOR:
        return None
    floor, _ = DELEGATE_FLOOR[metric]
    return (raw >= floor if METRICS[metric]["higher_is_better"] else raw <= floor)


def _norm_key(name: str) -> str:
    """Lowercased, alphanumerics only. Joins `Gemma 4 31B (Non-reasoning)` to
    `gemma-4-31b`... but NOT to `gemma-4-31b-it`, which is why a miss is a miss."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


#: Only AA splits a model into two mode records. LMArena and Vectara publish ONE row
#: per model with no mode marker at all, so a name that MUST carry AA's suffix to
#: resolve there cannot resolve here -- `qwen3827bnonreasoning` will never meet
#: LMArena's `qwen3827b`. That single naming mismatch is what made the best-measured
#: model in the fleet return UNKNOWN on six of ten jobs: not an absent source, a
#: suffix. So a lookup that misses retries once with the suffix removed.
#:
#: This is NOT the fuzzy matching `_record` refuses. Stripping is bounded to these two
#: literals, and the stripped key can only ever land on a record whose own name has no
#: mode marker -- `qwen3827b` cannot match `Qwen3.8 27B (Reasoning)` either, so a
#: `nothink` alias can never silently pick up a reasoning score. The existing
#: guarantee is untouched: `gemma431b` still does not match `gemma-4-31b-it`.
_MODE_SUFFIXES = (" (Non-reasoning)", " (Reasoning)")


def strip_mode(name: str) -> str:
    """`Qwen3.8 27B (Non-reasoning)` -> `Qwen3.8 27B`. Unchanged if unsuffixed."""
    for suffix in _MODE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


class Corpus:
    """The reference files, loaded once, with per-metric distributions."""

    def __init__(self, root: pathlib.Path | str | None = None):
        self.root = pathlib.Path(root or REFERENCES)
        self._files: dict[str, dict] = {}
        self._dists: dict[str, list[float]] = {}
        self._norm_index: dict[str, dict] = {}

    def _load(self, name: str) -> dict:
        if name not in self._files:
            p = self.root / name
            self._files[name] = (json.loads(p.read_text()) if p.exists()
                                 else {"models": {}, "_missing": str(p)})
        return self._files[name]

    def available(self) -> dict[str, bool]:
        return {n: (self.root / n).exists()
                for n in sorted({m["file"] for m in METRICS.values()})}

    def _record(self, file: str, published_name: str):
        """One model's record, by exact name then by a normalised key.

        Sources do not agree on naming -- AA says `Gemma 4 31B (Non-reasoning)`,
        LMArena says `gemma-4-31b`, Vectara says `google/gemma-4-31b-it`. The
        normalised form (lowercased, non-alphanumerics dropped) joins many of those.
        It is deliberately NOT fuzzy: a near-miss returns None rather than the
        closest thing, because a wrong join silently attributes one model's
        hallucination rate to another.
        """
        models = self._load(file).get("models") or {}
        if published_name in models:
            return models[published_name]
        key = _norm_key(published_name)
        idx = self._norm_index.get(file)
        if idx is None:
            idx = {}
            for name in models:
                nk = _norm_key(name)
                # Collisions are dropped, not arbitrated: two source names that
                # normalise the same cannot be told apart, so joining either would
                # be a guess.
                idx[nk] = None if nk in idx else name
            self._norm_index[file] = idx
        hit = idx.get(key)
        if hit is None:
            # Last resort: drop AA's mode suffix for the sources that carry no mode.
            # See `_MODE_SUFFIXES` for why this cannot cross modes or go fuzzy.
            stripped = _norm_key(strip_mode(published_name))
            if stripped != key:
                hit = idx.get(stripped)
        return models.get(hit) if hit else None

    def raw(self, metric: str, published_name: str):
        m = METRICS[metric]
        rec = self._record(m["file"], published_name)
        if not isinstance(rec, dict):
            return None
        if "path" in m:
            v = rec
            for step in m["path"]:
                v = v.get(step) if isinstance(v, dict) else None
        else:
            v = rec.get(m["field"])
        # "NOT_OBTAINED" is a deliberate sentinel in the reference files. It must
        # not be coerced to 0.0, which would read as a measured floor.
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        return v * m.get("scale", 1.0)

    def distribution(self, metric: str) -> list[float]:
        if metric not in self._dists:
            m = METRICS[metric]
            vals = []
            for rec in (self._load(m["file"]).get("models") or {}).values():
                if not isinstance(rec, dict):
                    continue
                if "path" in m:
                    v = rec
                    for step in m["path"]:
                        v = v.get(step) if isinstance(v, dict) else None
                else:
                    v = rec.get(m["field"])
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(float(v) * m.get("scale", 1.0))
            self._dists[metric] = sorted(vals)
        return self._dists[metric]

    def percentile(self, metric: str, value: float) -> tuple[float | None, int]:
        """Where `value` sits in the corpus, 0..1, 1 = best. Also returns n.

        Direction is applied here, so a hallucination RATE of 0.05 comes back near
        1.0. n is returned rather than logged because a percentile over six models
        is not the same claim as one over two hundred.
        """
        dist = self.distribution(metric)
        n = len(dist)
        if n < 5:
            return None, n
        below = sum(1 for d in dist if d < value)
        equal = sum(1 for d in dist if d == value)
        p = (below + equal / 2) / n
        if not METRICS[metric]["higher_is_better"]:
            p = 1.0 - p
        return p, n


def haircut(precision: str | None, skill: str) -> tuple[float, str]:
    """The literature-derived penalty for serving a quantised copy."""
    if not precision:
        return 0.0, "served at published precision"
    for key in ((precision, skill), (precision, "*")):
        if key in QUANT_HAIRCUT:
            return QUANT_HAIRCUT[key]
    return 0.0, f"no haircut recorded for {precision}"


def skill_score(corpus: Corpus, published_name: str, skill: str,
                precision: str | None) -> dict:
    """Best available evidence for one skill, after any haircut.

    When two sources cover the same skill they are NOT averaged -- they measure
    different things at different difficulty (Vectara's ~5-18% hallucination against
    AA-Omniscience's 49-97%). The more demanding source wins when both exist, since
    this is a safety screen and the pessimistic read is the useful one.
    """
    cut, cite = haircut(precision, skill)
    candidates = []
    for mid, m in METRICS.items():
        if m["skill"] != skill:
            continue
        v = corpus.raw(mid, published_name)
        if v is None:
            continue
        # 🔴 THE HAIRCUT IS APPLIED TO THE RAW METRIC, THEN PERCENTILED. Applying it
        # to the percentile instead was a units error, and it was wrong in both
        # directions: the literature reports degradations in ACCURACY, while a
        # percentile is a rank. An 11% accuracy drop is a 40-point percentile fall in
        # a dense part of the distribution and a 2-point fall in a sparse tail, so
        # multiplying the rank by (1 - cut) both understates and overstates the harm
        # depending where the model sits. Degrading the raw score and re-reading it
        # through the empirical CDF translates the published finding into whatever
        # rank change this distribution actually implies.
        raw_cut = float(v)
        if cut:
            # Direction matters: a hallucination RATE gets WORSE by rising.
            raw_cut = (raw_cut * (1.0 - cut) if m["higher_is_better"]
                       else raw_cut + (1.0 - raw_cut) * cut)
        p, n = corpus.percentile(mid, raw_cut)
        p_pub, _ = corpus.percentile(mid, float(v))
        if p is None:
            continue
        candidates.append({"metric": mid, "raw": v, "raw_after_haircut": raw_cut,
                           "pctile": p, "pctile_published": p_pub, "n": n,
                           "haircut": cut, "haircut_cite": cite,
                           # Judged on the post-haircut value: the floor is about
                           # what we would actually be running, not about the
                           # full-precision model someone else benchmarked.
                           "clears_floor": clears_floor(mid, raw_cut),
                           "floor": DELEGATE_FLOOR.get(mid, (None, ""))[0],
                           "note": m["note"]})
    if not candidates:
        return {"skill": skill, "pctile": None, "sources": [],
                "why": "no published metric for this skill"}
    chosen = min(candidates, key=lambda c: c["pctile"])
    return {"skill": skill, "pctile": chosen["pctile"],
            "clears_floor": chosen.get("clears_floor"),
            "chosen": chosen, "sources": candidates,
            "haircut": chosen.get("haircut", 0.0),
            "haircut_cite": chosen.get("haircut_cite", ""),
            "pctile_published": chosen.get("pctile_published"),
            "why": ("pessimistic of %d source(s)" % len(candidates)
                    + (f"; haircut applied to the raw metric"
                       if chosen.get("haircut") else ""))}


def _tier(scores: list[dict], alias_basis: str | None, any_haircut: bool) -> str:
    """Weakest-link tier, with DELEGATE gated on evidence quality.

    DELEGATE requires a measured correspondence and no haircut. A model we only
    reach through an AA *estimate*, a *proxy* variant, or a literature-assumed
    quantisation penalty can be worth trying -- that is VERIFY -- but it has not
    earned unchecked hand-off, and saying otherwise would repeat the mistake of
    treating an estimate as a measurement.
    """
    if any(s["pctile"] is None for s in scores) or not scores:
        return UNKNOWN
    worst = min(s["pctile"] for s in scores)
    if worst < _VERIFY_PCTILE:
        return DO_NOT
    # A percentile says "better than most of the corpus"; the floor says "good in
    # absolute terms". DELEGATE needs both, because the corpus contains a long weak
    # tail that makes the percentile flattering. `None` means no floor is declared
    # for that metric, which is not the same as clearing one -- refuse it.
    floors_ok = all(s.get("clears_floor") is True for s in scores)
    if (worst >= _DELEGATE_PCTILE and alias_basis == "measured"
            and not any_haircut and floors_ok):
        return DELEGATE
    return VERIFY


def assess(model_id: str, job: str, corpus: Corpus | None = None) -> dict:
    """Tier for one (model, job), with every input's provenance attached."""
    if job not in JOBS:
        raise KeyError(f"unknown job {job!r}; known: {sorted(JOBS)}")
    corpus = corpus or Corpus()
    alias = ALIASES.get(model_id)
    if alias is None:
        # Try the id as a published name directly -- that is how a hosted model
        # (Anthropic, gpt-oss) is looked up, since we run it at the vendor's own
        # precision.
        published, precision, basis = model_id, None, "direct"
    else:
        published, precision, basis = alias
    skills = JOBS[job]["skills"]
    scores = [skill_score(corpus, published, s, precision) for s in skills]
    any_cut = any(s.get("haircut") for s in scores)
    tier = _tier(scores, basis if alias else "measured", any_cut)
    score = (None if any(s["pctile"] is None for s in scores)
             else min(s["pctile"] for s in scores))

    return {
        "model": model_id, "published_as": published, "precision": precision,
        "alias_basis": basis, "job": job, "job_label": JOBS[job]["label"],
        "tier": tier,
        "score": score,
        "skills": scores,
        "limits": [
            "Percentiles are within the reference corpus, so they rank against "
            "published models -- not against an absolute standard.",
            "Most inputs are AA's own estimates or vendor self-reports.",
            "No source publishes quantised numbers; any haircut is "
            "assumed-from-literature, never measured.",
        ],
    }


def known_models() -> list[str]:
    return sorted(ALIASES)
