"""Place the models we can actually reach onto AA's intelligence-vs-cost plane.

ONE LOADER, for the same reason `chartdata.load_cells` is one loader: three chart
generators once re-globbed `evals/results` themselves, so a change of scoring
basis never reached them and regenerating produced byte-identical files while the
routing table moved. Anything that wants these coordinates imports from here.

THE FOUR ACCESS GROUPS, and where each comes from:

  gateway  ONLY a managed enterprise gateway (configured, not named here).
           Confirmed by asking the gateway's /v1/models rather than trusting
           `routing/roster.json`, which can be stale about ids.
  both     on the gateway AND on a paid outside account.
  outside  a paid outside account only.
  local    the oMLX fleet, scored in the mode we actually route (`nothink` ->
           AA's "Non-reasoning" row), the same discipline `ALIASES` in `refer.py`
           carries a correction note about.

           MEASURED across the 68 mode pairs in this corpus, reading the wrong
           row shifts the index by a median of +1.8 points and up to +11.5 --
           NOT the "~20 points" quoted elsewhere in this repo, which is about
           percentile positions in `refer`'s per-skill metrics and is a different
           unit. And the direction is NOT universal: reasoning scores LOWER in 4
           of the 68, Qwen3.5 9B among them (11.2 against 13.3), because on a
           small model reasoning spends tokens without buying accuracy. That the
           sign flips is the real argument for matching the served mode -- the
           error is not merely flattering, it is unpredictable.

THREE CONFIDENCE TIERS, because this repo forbids plotting an estimate as a
measurement (`references/artificial-analysis.json` says so in `_basis_note`, and
221 of its 259 records are estimates):

  MEASURED       AA ran it: a real index and a real cost.
  AA_ESTIMATED   AA publishes the number but flags it estimated, or publishes no
                 cost so we derive one from its published price.
  OUR_ESTIMATE   AA has no row at all, or the axis is ours to compute (every
                 local model's cost).

WHAT IS HONESTLY WEAK HERE, stated rather than buried:

  * A local model's cost is ELECTRICITY PLUS AMORTISED HARDWARE, and the hardware
    term dominates at roughly 18x the power. It rests on a machine price, a 3-year
    life and an 8h/day duty cycle -- the duty cycle being the most load-bearing
    guess, since 24h/day would cut the figure threefold. See
    `MACHINE_USD_PER_HOUR`. Pricing electricity alone was a real defect: it made
    local look 4-6x cheaper than anything purchasable, and correcting it reversed
    the chart's headline.
  * The power half rests on an ASSUMED draw. `powermetrics` needs a password, so
    nothing was measured; Apple publishes only a 480 W maximum continuous rating
    for this enclosure, which is a supply ceiling and not a draw. See
    `POWER_DELTA_W`.
  * AA's cost is overwhelmingly INPUT tokens ($2.40 of $2.49 for Qwen3.8 27B) and
    `routing/throughput.json` measures generation on SHORT prompts only, saying so
    in its own limits block. So local wall-clock excludes prompt processing and
    understates. `PREFILL_MULTIPLIER` carries that as a band, not a point.
  * Nova's cost is inferred from published price times a tokens-per-task ratio
    whose spread across comparable models is wide. The band shows it.

Every one of those produces a RANGE, and the renderer draws the range. A point
estimate would be the lie.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import statistics
import sys
from typing import Iterable

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
AA_COST = REPO / "references" / "artificial-analysis-cost.json"
LMARENA = REPO / "references" / "lmarena.json"
THROUGHPUT = REPO / "routing" / "throughput.json"
#: HuggingFace's answers to two questions the AA corpus cannot answer: does an MLX build
#: exist (oMLX cannot load GGUF), and what does the model REALLY weigh. Written by
#: `tools/hf_mlx_scan.py`; absent is fine, the estimates below fall back to nominal.
MLX_AVAILABILITY = REPO / "references" / "mlx-availability.json"

MEASURED = "measured"
AA_ESTIMATED = "aa_estimated"
OUR_ESTIMATE = "our_estimate"
TIERS = (MEASURED, AA_ESTIMATED, OUR_ESTIMATE)

#: Four access groups, not three. BOTH exists because a model reachable through the
#: gateway AND through an outside account is a materially different proposition
#: from one locked to either side. Collapsing it into GATEWAY hid that.
GATEWAY, BOTH, OUTSIDE, LOCAL = "gateway", "both", "outside", "local"
#: Open weights we could install but have not. Drawn distinctly because their
#: cost AND speed are estimates, never measurements.
LOCAL_CANDIDATE = "local_candidate"
GROUPS = (GATEWAY, BOTH, OUTSIDE, LOCAL, LOCAL_CANDIDATE)

# --------------------------------------------------------- local cost model --

#: Extra wall power the machine draws while generating, in watts, as (low, high).
#:
#: THIS IS AN ASSUMPTION, NOT A MEASUREMENT, and it is the weakest number in this
#: module. `powermetrics` is the only instrument on Apple silicon and it requires
#: a password, so no reading was taken. Apple's published figure for this
#: enclosure is "Maximum continuous power: 480W", which is what the
#: supply can deliver, not what inference costs -- quoting it as a draw would
#: overstate by roughly 4x.
#:
#: The band is the plausible package-level delta for sustained GPU inference on
#: a high-end desktop above an idle one that is already powered on. Replace it with one
#: wall-meter reading and this whole axis tightens.
POWER_DELTA_W = (80.0, 120.0)

#: USD per kWh. California commercial rate, order-of-magnitude. The result is
#: linear in this, and it is swamped by POWER_DELTA_W and PREFILL_MULTIPLIER.
PRICE_PER_KWH = 0.25

#: Machine cost amortised over its working life, in USD per hour of use.
#:
#: 🔴 THIS DOMINATES, AND ITS ABSENCE WAS A REAL DEFECT. An earlier version priced
#: local inference as electricity alone, which put a 27B model at about $0.013 per
#: task and made local look 4-6x cheaper than the cheapest purchasable model. That
#: figure was disbelieved, rightly: the electricity arithmetic was
#: correct to three checks, but it treated the machine as free. Hardware is
#: roughly 18x the electricity, and including it REVERSES the conclusion -- local
#: becomes dearer than GPT-6 Luna at max effort while scoring 17 index points below
#: it.
#:
#: The assumptions, so they can be argued with rather than guessed at:
#:   price   a high-end desktop, as configured (a placeholder; set your own).
#:   life    3 years before it is replaced or repurposed.
#:   duty    8 hours a day of actual inference. NOT 24: the machine may be on all the
#:           time, but it is not generating all the time, and amortising over
#:           wall-clock hours it spends idle would understate by 3x.
#: At 24h/day this falls to $0.15/h and at 4h/day rises to $0.55/h, so the duty
#: cycle is the single most load-bearing guess here.
MACHINE_PRICE_USD = 4000.0
MACHINE_LIFE_YEARS = 3.0
MACHINE_DUTY_HOURS_PER_DAY = 8.0
MACHINE_USD_PER_HOUR = MACHINE_PRICE_USD / (
    MACHINE_LIFE_YEARS * 365.0 * MACHINE_DUTY_HOURS_PER_DAY)

#: Multiplier on decode time to account for PROMPT PROCESSING, as (low, high).
#:
#: AA's index is input-heavy -- its canonical token counts run about 39 input
#: tokens per output token -- and `routing/throughput.json` measures decode on a
#: ~120-token prompt, explicitly warning its numbers must not be used where
#: prompt processing dominates. Prefill on this hardware is far faster per token
#: than decode, so the two contributions land within an order of magnitude of
#: each other. 1.0 is "decode only", the floor; 3.0 allows prefill to cost twice
#: decode again.
PREFILL_MULTIPLIER = (1.0, 3.0)


def local_seconds(output_tokens: float, tok_per_s: float
                  ) -> tuple[float, float, float]:
    """(low, mid, high) wall-clock SECONDS for one index task on this machine.

    Decode time from our measured rate, widened by the prefill band because the
    index is input-heavy and `throughput.json` measures short prompts only. Unlike
    AA's published figure this contains no network or queueing latency -- there is
    none to contain, which is a real advantage of local and not a measurement gap.
    """
    if tok_per_s <= 0 or output_tokens <= 0:
        raise ValueError("output tokens and tok/s must both be positive")
    decode = output_tokens / tok_per_s
    lo, hi = decode * PREFILL_MULTIPLIER[0], decode * PREFILL_MULTIPLIER[1]
    return lo, (lo * hi) ** 0.5, hi


def _local_cost_usd(output_tokens: float, tok_per_s: float
                    ) -> tuple[float, float, float]:
    """Return (low, mid, high) USD to run one AA index task on this machine.

    ELECTRICITY PLUS HARDWARE. Electricity alone is a floor that omits the largest
    term: at 15.6 tok/s a 30k-token task occupies the machine for about 32 minutes,
    which is roughly $0.24 of amortised hardware against $0.013 of power.

    Both terms are linear in occupancy, so the extremes of the power and prefill
    bands still give the extremes of the total -- no sampling needed. Hardware has
    no band of its own here; its uncertainty lives in the constants above and is
    stated there rather than smeared into an interval that would imply we measured
    a spread.
    """
    if tok_per_s <= 0 or output_tokens <= 0:
        raise ValueError("output tokens and tok/s must both be positive")
    decode_hours = output_tokens / tok_per_s / 3600.0

    def total(prefill: float, watts: float) -> float:
        hours = decode_hours * prefill
        return hours * (watts / 1000.0 * PRICE_PER_KWH + MACHINE_USD_PER_HOUR)

    lo = total(PREFILL_MULTIPLIER[0], POWER_DELTA_W[0])
    hi = total(PREFILL_MULTIPLIER[1], POWER_DELTA_W[1])
    return lo, (lo * hi) ** 0.5, hi          # geometric mid: the axis is log


# ------------------------------------------------------------------ the fleet --

#: (our label, AA row name, precision) for the local fleet. The AA name is the
#: NON-REASONING row on purpose -- see the module docstring.
#: The OBLITERATED 4-bit copy is deliberately ABSENT (maintainer, 2026-09-30): the chart
#: has an institutional audience and an abliterated -- safety-training-removed -- model is not
#: something to put in front of it, whatever its throughput.
#: DROPPED to declutter (maintainer, 2026-09-30): `gemma-4-31b-it-8bit` (index 13.9 at
#: $0.52 -- the worst of both axes). It was then removed from the local
#: install, so it is not a chart decision any more.
#:
#: NOT dropped, though a strict Pareto filter would remove them: the two 27B Qwens.
#: They are dominated only by CANDIDATES whose cost and speed are our estimates, and
#: deleting a measured model on the strength of an estimate inverts the evidence
#: hierarchy this whole module is built on.
#: ✅ THIS LIST IS THE WHOLE INSTALLED FLEET, matching oMLX's own
#: `/v1/models`. It was once one shorter until GLM-4.7-Flash-8bit
#: was admitted; keep it reconciled against the server rather than against memory,
#: because the HuggingFace cache keeps 4 KB directory husks after a deletion and they
#: read exactly like installs.
#:
#: GLM was first excluded for having only an estimated AA index, then admitted:
#: estimated values may be plotted if marked as estimates.
#: The old reasoning was that `tier` would misreport — but it does not, because
#: `load_fleet` already reads AA's own `intelligenceIndexIsEstimated` and tiers the
#: point `AA_ESTIMATED`, which the chart draws as a distinct mark and names "their
#: estimate" in its provenance legend. The honest treatment of an estimate was always
#: to MARK it, not to delete the model; exclusion silently cost the chart the
#: second-fastest thing we own. `test_no_estimate_is_presented_as_a_measurement` still
#: holds and is what makes admitting it safe: it forbids an estimated index being
#: tiered MEASURED, which is a different claim from forbidding it on the chart at all.
#:
#: Removed from the local install, both justified on SCORE: `Qwen3.6-27B-8bit` (Qwen3.8
#: dominates it at every matched effort — 20.2 vs 19.8 non-reasoning, 26.2–33.7 vs 21.4
#: reasoning) and `gemma-4-31b-it-8bit` (lowest index AND slowest). Two
#: further removals were PROPOSED and rejected because their reasons were
#: not score: "declutter" for GLM-4.7-Flash and "safety-stripped" for the abliterated
#: 4-bit copy. Both are kept on the chart.
#:
#: An entry here REQUIRES a measured `warm_tok_per_s` in `routing/throughput.json` or
#: `local_cost_usd` raises. That guard caught K2 Horizon being added before it was
#: benchmarked, which is exactly its job.
LOCAL_FLEET = (
    ("Qwen3.8-27B-8bit", "Qwen3.8 27B (Non-reasoning)", "8bit"),
    ("Qwen3.5-9B-MLX-4bit", "Qwen3.5 9B (Non-reasoning)", "4bit"),
    # Restored to the chart after being dropped to declutter.
    # It earns its place twice over: it was kept because "safety-stripped"
    # is not a score reason, and it is the THIRD DENSE model the bandwidth calibration
    # needs — `test_the_bandwidth_model_reproduces_the_measured_fleet` requires three and
    # deleting Qwen3.6 and gemma left two. Same weights as the 8-bit row above at a
    # different quantisation, so AA's index is shared and the 4-bit haircut is what
    # separates them on the chart.
    ("Qwen3.8-27B-OBLITERATED-OptiQ-4bit", "Qwen3.8 27B (Non-reasoning)", "4bit"),
    # Installed later, the top-scoring candidate at index 25.3 — and the first
    # local model to beat Qwen3.8 27B non-reasoning (20.2) on AA's index. Estimated at
    # ~47 tok/s from bandwidth; MEASURED 44.1, so `estimate_local_rate` was 7% high on
    # its first out-of-sample MoE test. It needs oMLX's per-model `trust_remote_code`
    # (ships a custom `k2_horizon.py` architecture module, which imports only
    # math/dataclasses/typing/mlx — no I/O, network or exec); trust is enabled per model
    # for mlx-community sources.
    #
    # Ling-3.0-flash-VL (index 24.6) was the other intended install and is BLOCKED: no
    # MLX build exists at any quantisation, only GGUF. A format gate the cost model
    # cannot see, so it will keep reappearing as the top candidate.
    ("K2-Horizon-MoVA-36B-A4B-8bit", "K2 Horizon MoVA 36B A4B", "8bit"),
    # Admitted on the rule that estimated values may be
    # charted. AA flags its index estimated, so `load_fleet` tiers this point
    # AA_ESTIMATED and the chart marks it "their estimate" rather than drawing it as a
    # measurement. At 58.2 tok/s measured it is the second-fastest model in the fleet,
    # behind Qwen3.5-9B's 78.8 and nearly 4x Qwen3.8-27B's 15.3 — which is why its
    # absence mattered: on cost-and-intelligence axes a model whose case is SPEED
    # looks dominated, and that is the two-axis trap recorded in this repo's CLAUDE.md.
    ("GLM-4.7-Flash-8bit", "GLM-4.7-Flash (Non-reasoning)", "8bit"),
)

# ------------------------------------------------- what we could install locally --

#: Effective memory bandwidth for generation on this machine, GB/s.
#:
#: MEASURED, not assumed. Across four dense local models `tok/s x weight-GB` reads
#: 403, 437, 445 and 457 GB/s -- tight enough to treat generation as
#: memory-bandwidth bound at about 82% of the machine's theoretical memory bandwidth. That
#: is what makes a model we have NOT installed estimable at all.
LOCAL_BANDWIDTH_GB_S = 432.0

#: How much more than its active weights a mixture-of-experts effectively reads per
#: token. RESTS ON A SINGLE MEASUREMENT and is the weakest constant here:
#: GLM-4.7-Flash (3B active of 31B) measures 61.3 tok/s, implying 7.0 GB effective
#: against 3.0 GB active. Routing, shared attention and less contiguous reads
#: account for the gap. One point cannot separate a multiplier from an offset, so
#: any MoE estimate below carries a wide band and says so.
MOE_READ_FACTOR = 2.3

#: Weight budget in GB. Total memory less room for KV cache, the OS and headroom.
#: TOTAL parameters must fit -- an MoE reads only its active experts per token but
#: still has to hold all of them resident. Sizing memory by ACTIVE params was a real
#: bug here: it admitted a 1,020B model that needs ~560 GB.
LOCAL_WEIGHT_BUDGET_GB = 95.0

_BYTES_PER_PARAM = {"8bit": 1.0, "4bit": 0.55}


def mlx_index(path: pathlib.Path | None = None) -> dict:
    """HuggingFace's view of each base model: is it runnable here, and how big is it.

    `{}` when the sidecar is absent, so a fresh clone still produces a chart — on nominal
    estimates, which is what the whole fleet ran on before 2026-10-01.

    Three states per entry, and conflating them is the trap:
      * `repo` set with a `gb`  — runnable, and the size is MEASURED (hf-mem over HTTP
        Range, validated to the byte against a disk measurement).
      * `repo` null, `mlx_repos == 0` — nothing exists under that name on
        mlx-community. `Ling-3.0-flash-VL` is the case that motivated this: index 24.6,
        top candidate for weeks, GGUF only, oMLX cannot load it.
      * `repo` null, `mlx_repos > 0` — builds exist but the scanner's name matcher
        rejected them all. That is UNKNOWN, not unavailable: the matcher is deliberately
        strict about variant builds (abliterated/DWQ/REAP) and it mismatches real repos
        too. Such a candidate is kept and flagged, never silently dropped.
    """
    try:
        return _load(path or MLX_AVAILABILITY).get("models") or {}
    except (OSError, ValueError):
        return {}


def estimate_local_rate(total_b: float, active_b: float | None,
                        precision: str, weight_gb: float | None = None) -> float:
    """Estimated warm tok/s on this machine for a model we have not installed.

    `weight_gb`, when given, is the model's MEASURED on-disk size and overrides
    `_BYTES_PER_PARAM`. Pass it whenever it is known — an estimate must not displace a
    measurement, and here the nominal is materially wrong:

    | model | params | nominal GB | actual GB | actual B/param |
    |---|---|---|---|---|
    | `Qwen3.8-27B-OBLITERATED-OptiQ-4bit` | 27B | 14.9 | **19.0** | 0.70 |
    | `Qwen3.5-9B-MLX-4bit`                |  9B |  5.0 |   5.6 | 0.62 |

    Both exceed the 0.55 the table below assumes, OptiQ-style 4-bit badly. Estimating
    the 27B from nominal gives 29 tok/s against 19.6 measured — a 48% miss, outside the
    calibration band — while its real 19 GB gives 22.7, a 16% miss and inside. The
    defect was invisible while the only installed 4-bit model was the small one, whose
    absolute error is small enough to hide inside the band.
    """
    is_moe = bool(active_b) and active_b < total_b * 0.9
    if weight_gb:
        # Measured total size, apportioned to what an MoE actually reads per token.
        read_gb = (weight_gb * (active_b / total_b) * MOE_READ_FACTOR
                   if is_moe and total_b else weight_gb)
    else:
        bpp = _BYTES_PER_PARAM[precision]
        read_gb = (active_b * MOE_READ_FACTOR if is_moe else total_b) * bpp
    if read_gb <= 0:
        raise ValueError("a model that reads no weights cannot be timed")
    return LOCAL_BANDWIDTH_GB_S / read_gb


def local_candidates(models: dict | None = None, top_n: int = 6) -> list[Point]:
    """Open-weight models we could install, to give the local frontier a shape.

    DERIVED from the corpus rather than hand-listed, for the same reason the GPT
    tiers are: a hand list silently went stale within the hour last time.

    Admits a row if AA publishes an index — **measured OR estimated** — its TOTAL
    weights fit `LOCAL_WEIGHT_BUDGET_GB` at 8-bit or 4-bit, and it is not already
    installed. Cost comes from the same `_local_cost_usd` the installed fleet uses, on
    an ESTIMATED rate -- so every one of these is OUR_ESTIMATE, never measured.

    **Estimated indices are admitted**, marked as estimates. Requiring a
    measured index left a pool of 79 out of 371 open-weight rows, which is a narrow
    window on what could be installed.

    🔴 **An estimate still may not delete a measurement.** The Pareto filter judges a
    measured-index candidate only against other measured-index candidates, so AA's
    extrapolation can never retire a row AA actually ran. An estimated candidate is
    fair game for anything. This is the same rule that keeps candidates from being
    filtered against the installed fleet at all.

    There is NO vendor, country or licence filter here, and that is deliberate (the maintainer's
    standing ruling: pick by score, never by licence). Note separately that the pool is
    bounded by AA's coverage, not by HuggingFace's: LMArena carries 409 models and
    Vectara 108, but neither publishes a parameter count, so neither can answer whether
    a model fits in 128 GB. AA is the only source here that can size one.
    """
    models = models if models is not None else _load(AA_COST)["models"]
    # Exclude by BASE name, not by exact row. Matching exactly admitted
    # "Qwen3.8 27B (Xhigh)" as something to install while we already run
    # "Qwen3.8 27B (Non-reasoning)" -- the same weights at a different effort, which
    # is a routing decision and not a download. Same trap as the GPT ladder.
    installed = {aa.split(" (")[0] for _l, aa, _p in LOCAL_FLEET}
    hub = mlx_index()
    out: list[Point] = []
    #: Scored well enough to be a candidate and NOT RUNNABLE here. Reported rather than
    #: silently dropped: a model vanishing from the list with no reason is how
    #: Ling-3.0-flash-VL stayed top candidate for weeks while being unloadable.
    unrunnable: list[str] = []
    for name, rec in models.items():
        if name.split(" (")[0] in installed or not rec.get("isOpenWeights"):
            continue
        if rec.get("intelligenceIndex") is None:
            continue              # no score at all is still out: nothing to rank on
        # 🔴 Score a candidate in the mode we would SERVE it in, which is the same
        # discipline LOCAL_FLEET follows and two tests enforce for installed models.
        # Without it the list ranked reasoning rows: `Qwen3.5 27B (Reasoning)` at 22.9
        # appeared to beat our installed Qwen3.8 27B at 20.2, which is a comparison
        # across two different modes. Thinking was MEASURED to hurt local models on our
        # jobs (the 27B fell from 80% to 17% on garbled names), so a reasoning row is
        # not a number we could collect.
        base_name = name.split(" (")[0]
        if "(Reasoning)" in name and f"{base_name} (Non-reasoning)" in models:
            continue
        est = bool(rec.get("intelligenceIndexIsEstimated"))
        total = rec.get("parameters")
        if not total:
            continue
        active = rec.get("inferenceParametersActiveBillions")

        # --- HuggingFace first, nominal only as a fallback.
        hf = hub.get(name.split(" (")[0]) or {}
        real_gb = hf.get("gb")
        if hf and not hf.get("repo") and hf.get("mlx_repos") == 0:
            # Nothing exists on mlx-community under this name, so oMLX cannot load it
            # however well it scores. This is the Ling-3.0-flash-VL case.
            unrunnable.append(name)
            continue
        if real_gb:
            # A real size answers the fit question properly. `params x nominal` said the
            # abliterated 27B was 14.9 GB when it is 19.0, and that 27% error became a
            # 48% error in the speed estimate.
            precision = hf.get("quant") or "8bit"
            if real_gb > LOCAL_WEIGHT_BUDGET_GB:
                continue
        else:
            precision = next((q for q in ("8bit", "4bit")
                              if total * _BYTES_PER_PARAM[q] <= LOCAL_WEIGHT_BUDGET_GB),
                             None)
            if precision is None:
                continue
        rate = estimate_local_rate(float(total), active, precision,
                                   weight_gb=real_gb)
        tokens = _tokens_per_task(models, prefer=(name,))
        lo, mid, hi = _local_cost_usd(tokens, rate)
        tlo, tmid, thi = local_seconds(tokens, rate)
        y = float(rec["intelligenceIndex"])
        cut = QUANT_HAIRCUT.get(precision, 0.0)
        out.append(Point(
            label=name, group=LOCAL_CANDIDATE, tier=OUR_ESTIMATE,
            x=mid, y=y, x_lo=lo, x_hi=hi,
            y_lo=y * (1.0 - cut) if cut else y, y_hi=y,
            basis=(f"NOT installed. {total:g}B total"
                   + (f" / {active:g}B active (MoE)" if active and active < total * 0.9
                      else " dense")
                   + f" at {precision}; rate ESTIMATED at {rate:.0f} tok/s from "
                     f"measured {LOCAL_BANDWIDTH_GB_S:.0f} GB/s bandwidth"
                   + (f"; {real_gb:g} GB real (hf-mem)" if real_gb else
                      "; size from nominal bytes/param, which runs ~27% low on 4-bit")
                   + ("; no plain MLX build matched, runnability UNCONFIRMED"
                      if hf and not hf.get("repo") else "")
                   + ("; AA index is ESTIMATED, not run" if est else "")),
            aa_name=name, secs=tmid, secs_lo=tlo, secs_hi=thi,
            index_estimated=est))
    # PARETO-FILTER the candidates against each other (maintainer, 2026-09-30): a
    # candidate that another candidate beats on BOTH cost and index defines nothing
    # and only crowds the left edge. Filtered among candidates only -- comparing
    # them against the installed fleet would let an estimate delete a measurement.
    #
    # And within the candidates, the same rule applies one level down now that AA's
    # estimated indices are admitted: a measured candidate is judged ONLY against other
    # measured candidates, so an extrapolation cannot retire a row AA actually ran.
    measured = [q for q in out if not q.index_estimated]

    def dominated(p: Point, pool: list[Point]) -> bool:
        return any(q.x < p.x * 0.999 and q.y > p.y + 1e-9 for q in pool)

    front = [p for p in out
             if not dominated(p, out if p.index_estimated else measured)]
    if unrunnable:
        # Visible, not silent. A capped or filtered list that does not say what it
        # dropped reads as "this is everything".
        print(f"local_candidates: {len(unrunnable)} scored model(s) excluded as having "
              f"no MLX build oMLX can load, e.g. {unrunnable[:3]}", file=sys.stderr)
    return sorted(front, key=lambda p: -p.y)[:top_n]

#: Quantisation haircut on the composite index, mirroring `refer.QUANT_HAIRCUT`'s
#: general ("*") entries so the two cannot drift apart silently. 8-bit is 0.00
#: there (arXiv:2505.20276 measures ~0.8%), which is why only the 4-bit models
#: draw a visible pair -- a zero-length connector would be noise.
QUANT_HAIRCUT = {"8bit": 0.00, "4bit": 0.11}

#: Models reachable ONLY through the managed enterprise gateway. Load-balancer
#: aliases collapse onto their base id and embedding models are excluded.
#: "Flagship" is read as the highest-effort variant AA publishes.
#: The membership of each fleet is configuration: the entries below are examples
#: to be replaced with whatever your own gateway and accounts actually serve.
GATEWAY_FLEET: tuple[tuple[str, str | None], ...] = (
    ("Gemini 3.5 Flash", "Gemini 3.5 Flash (High)"),
    ("Claude Opus 5", "Claude Opus 5 (Max)"),
    ("Claude Opus 4.8", "Claude Opus 4.8 (Max)"),
    ("Claude Sonnet 5", "Claude Sonnet 5 (Max)"),
    ("Claude Sonnet 4.5", None),        # absent from AA entirely; estimated below
)

#: Reachable BOTH ways: on the gateway and also through an outside subscription.
#: Empty by default; the group is kept so the next dual-reachable model has a home.
BOTH_FLEET: tuple[tuple[str, str | None], ...] = ()

#: Reachable only through an outside subscription (example entries; replace with
#: what your own account serves). A model you can reach but choose not to route
#: still belongs on this chart: it answers "what can we reach".
OUTSIDE_FLEET = (
    ("Claude Opus 5.5", "Claude Opus 5.5 (Max, Default Fallback)"),
    ("Claude Sonnet 5.5", "Claude Sonnet 5.5 (Max, Default Fallback)"),
    ("Claude Fable 5.1", "Claude Fable 5.1 (Max, Default Fallback)"),
    ("Claude 4.5 Haiku", "Claude 4.5 Haiku (Reasoning)"),
    # OpenAI models are NOT hand-listed -- see `gpt_fleet`. Hand-listing them
    # silently dropped GPT-5.6 Terra while including its siblings Sol and Luna, and
    # dropped GPT-5.5, which the account's catalogue read had returned.
)


def gpt_fleet(models: dict) -> tuple[tuple[str, str], ...]:
    """Every OpenAI tier the corpus measures, as (label, flagship row).

    DERIVED, NOT LISTED, and that is the point. A hand-written list of tiers went
    stale the moment it was written: it carried GPT-5.6 Sol and GPT-5.6 Luna while
    omitting GPT-5.6 Terra, their direct sibling, and omitted GPT-5.5 even though
    ChatGPT's own catalogue read had returned it. Deriving makes a missing tier
    impossible rather than merely unlikely, and a test pins that nothing is absent.

    An example subscription is assumed to reach the whole OpenAI lineup, so it is
    treated as reachable. AA publishes NO row named "Pro" for any GPT -- the tiers
    are Astra > Sol > Terra > Luna, size classes rather than products, confirmed by
    ChatGPT's catalogue mapping slug `gpt-5-6-mini` to the title "GPT-5.6 Luna".
    "Pro" is a plan name.

    CAVEAT worth knowing: this includes older small tiers (GPT-5 mini, GPT-5.4
    nano) that the ChatGPT interface may no longer offer even though the API still
    serves them. They land cheap and low-scoring, so they widen the picture rather
    than distort it -- but if the intent is "what the UI offers today", narrow this
    to the current generations rather than re-hand-listing.
    """
    best: dict[str, tuple[int, str]] = {}
    for name, rec in models.items():
        if not name.startswith("GPT"):
            continue
        if not rec.get("costPerTask") or rec.get("intelligenceIndexIsEstimated"):
            continue
        base = name.split(" (")[0]
        rank = _effort_rank(name)
        # Rank -1 keeps a tier that publishes only a non-effort row (GPT-5.5
        # Instant) rather than dropping it for having no ladder.
        key = rank if rank is not None else -1
        if base not in best or key > best[base][0]:
            best[base] = (key, name)
    return tuple((base, row) for base, (_k, row) in sorted(best.items()))

#: Models with a row in BOTH sources, used to map human-preference Elo onto AA's
#: index for the one model AA does not cover. Same vendor on purpose: a
#: cross-vendor fit would absorb vendor-specific preference effects.
#:
#: These two sources genuinely DISAGREE in places -- Elo ranks Sonnet 4.6 above
#: Sonnet 5 while AA ranks the reverse -- which is why the result is a band and is
#: tiered OUR_ESTIMATE rather than presented as a reading.
ELO_ANCHORS = (
    ("claude-haiku-4-5-20251001", "Claude 4.5 Haiku (Reasoning)"),
    ("claude-sonnet-5-high", "Claude Sonnet 5 (High)"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Max)"),
    ("claude-opus-4-8-high", "Claude Opus 4.8 (Max)"),
    ("claude-opus-5-high", "Claude Opus 5 (High)"),
    ("claude-opus-5.5-high",
     "Claude Opus 5.5 (High, Default Fallback)"),
)

#: The model estimated through ELO_ANCHORS, and the AA row whose published PRICE
#: it shares (identical vendor pricing), used for its cost.
SONNET_45 = {
    "label": "Claude Sonnet 4.5",
    "lmarena_key": "claude-sonnet-4-5-20250929",
    "price_twin": "Claude Sonnet 4.6 (Max)",
}


@dataclasses.dataclass(frozen=True)
class Point:
    """One model's position, with an interval on any axis we did not read.

    `tier` describes the provenance of the INTELLIGENCE score (y) -- the claim the
    chart is actually about. Cost provenance is not folded into it, because it is
    already visible as the x interval: a model whose cost we derived has a wide
    bar and a model AA billed has none. Folding both into one label would flatten
    every local model to the same marker and hide that AA really did run one of
    them.

    `y_haircut`, where present, is OURS -- a literature-cited correction for the
    quantisation we serve, never a reading -- so a renderer should draw that
    endpoint in the our-estimate style regardless of `tier`.
    """
    label: str
    group: str
    tier: str
    x: float
    y: float
    x_lo: float
    x_hi: float
    y_lo: float
    y_hi: float
    basis: str
    aa_name: str | None = None
    #: Index after the quantisation haircut, when one applies and is non-zero.
    y_haircut: float | None = None
    #: END-TO-END seconds for one index task: AA's own wall-clock, which includes
    #: queueing and network latency, not just generation. `None` where no source
    #: publishes one -- about a sixth of the cost-bearing corpus. A model can be
    #: cheap and clever and still take a quarter of an hour, which is the whole
    #: reason this is a separate axis rather than a footnote.
    secs: float | None = None
    secs_lo: float | None = None
    secs_hi: float | None = None
    #: True when AA ESTIMATED the intelligence index rather than running it. Separate
    #: from `tier`, which for a candidate is always OUR_ESTIMATE because the cost and
    #: speed are ours -- this says the Y VALUE is AA's extrapolation. It exists so the
    #: Pareto filter can refuse to let an estimate delete a measurement.
    index_estimated: bool = False

    @property
    def has_secs(self) -> bool:
        return self.secs is not None and self.secs > 0

    @property
    def has_secs_range(self) -> bool:
        return (self.secs_lo is not None and self.secs_hi is not None
                and self.secs_hi > self.secs_lo * 1.001)

    @property
    def has_x_range(self) -> bool:
        return self.x_hi > self.x_lo * 1.001

    @property
    def has_y_range(self) -> bool:
        return self.y_hi > self.y_lo + 1e-9


def corpus_date() -> str:
    """When the published corpus was retrieved.

    Read from the FILE, never from today's date: it dates the data, not the render.
    A chart reproducing a third party's plane that moves weekly is worthless
    without this, and nothing else on the page answers "is it still true".
    """
    d = _load(AA_COST).get("_retrieved")
    return str(d) if d else "date unrecorded"


def _load(path: pathlib.Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. For the AA corpus run "
            "`python3 tools/charts/aa_cost_fetch.py`.")
    return json.loads(path.read_text())


def _cost(rec: dict) -> float | None:
    v = rec.get("costPerTask")
    return float(v) if isinstance(v, (int, float)) else None


def _secs(rec: dict) -> float | None:
    v = rec.get("secondsPerTask")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def load_published(models: dict | None = None) -> list[Point]:
    """Every AA model carrying BOTH a measured index and a real cost.

    This is the faded background cloud. Records AA flags estimated are excluded
    outright -- they carry no cost anyway, so the cost-bearing subset and the
    measured subset happen to coincide, and the exclusion costs no points.
    """
    models = models if models is not None else _load(AA_COST)["models"]
    out: list[Point] = []
    for name, rec in models.items():
        c = _cost(rec)
        if c is None or c <= 0 or rec.get("intelligenceIndexIsEstimated"):
            continue
        y = float(rec["intelligenceIndex"])
        t = _secs(rec)
        out.append(Point(label=name, group="published", tier=MEASURED,
                         x=c, y=y, x_lo=c, x_hi=c, y_lo=y, y_hi=y,
                         basis="AA measured", aa_name=name,
                         secs=t, secs_lo=t, secs_hi=t))
    if not out:
        raise ValueError(
            "no published model carries both a measured index and a cost; the "
            "payload shape has changed and every chart built on this is empty")
    return out


def _tokens_per_task(models: dict, prefer: Iterable[str]) -> float:
    """Output tokens for one AA index task, from the first row that states it.

    Falls back to the median across all rows that carry the field, because a
    local model's cost must not silently become zero just because AA happens not
    to publish a token count for its exact row.
    """
    for name in prefer:
        rec = models.get(name) or {}
        v = rec.get("outputTokensPerTask")
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    allv = [float(v["outputTokensPerTask"]) for v in models.values()
            if isinstance(v.get("outputTokensPerTask"), (int, float))
            and v["outputTokensPerTask"] > 0]
    if not allv:
        raise ValueError("no AA row states outputTokensPerTask; cannot time a "
                         "local task")
    return statistics.median(allv)


def _price_to_cost_ratio(models: dict, non_reasoning: bool) -> tuple[float, float, float]:
    """(p25, median, p75) of cost-per-task divided by blended price per Mtoken.

    Used to give a cost to a model AA prices but never ran. Split by reasoning
    mode because a reasoning model emits far more tokens per task, and mixing the
    two inflates the spread to no purpose.
    """
    rs = []
    for name, rec in models.items():
        c, p = _cost(rec), rec.get("price1mBlended0To3To1")
        if not c or not isinstance(p, (int, float)) or p <= 0:
            continue
        if non_reasoning != ("Non-reasoning" in name):
            continue
        rs.append(c / p)
    if len(rs) < 3:
        # Too thin to quote quartiles from; fall back to the whole field rather
        # than invent a tight band out of two points.
        rs = [(_cost(r) or 0) / r["price1mBlended0To3To1"] for r in models.values()
              if _cost(r) and isinstance(r.get("price1mBlended0To3To1"), (int, float))
              and r["price1mBlended0To3To1"] > 0]
    rs.sort()
    return rs[len(rs) // 4], statistics.median(rs), rs[3 * len(rs) // 4]


def _estimate_sonnet_45(models: dict, arena: dict) -> Point:
    """Position the one gateway model AA does not cover, via human-preference Elo.

    Both axes are ours, so this is OUR_ESTIMATE and both carry a range. The y
    range comes from the two anchors that bracket its Elo; the x range from the
    price-to-cost spread applied to the price it shares with Sonnet 4.6.
    """
    pairs = []
    for key, aa_name in ELO_ANCHORS:
        a = (arena.get(key) or {}).get("overall") or {}
        rec = models.get(aa_name) or {}
        if isinstance(a.get("score"), (int, float)) and rec.get("intelligenceIndex"):
            pairs.append((float(a["score"]), float(rec["intelligenceIndex"])))
    if len(pairs) < 2:
        raise ValueError("fewer than two Elo/index anchors resolved; cannot "
                         "estimate a model AA does not publish")
    pairs.sort()
    target = (arena.get(SONNET_45["lmarena_key"]) or {}).get("overall") or {}
    if not isinstance(target.get("score"), (int, float)):
        raise ValueError(f"{SONNET_45['lmarena_key']} carries no Elo; the one "
                         "independent anchor for this model is gone")
    elo = float(target["score"])

    below = [p for p in pairs if p[0] <= elo] or [pairs[0]]
    above = [p for p in pairs if p[0] >= elo] or [pairs[-1]]
    lo_elo, lo_ii = below[-1]
    hi_elo, hi_ii = above[0]
    if hi_elo > lo_elo:
        t = (elo - lo_elo) / (hi_elo - lo_elo)
        y = lo_ii + t * (hi_ii - lo_ii)
    else:
        y = lo_ii
    # The bracketing anchors ARE the uncertainty: the two sources disagree on
    # ordering inside this range, so nothing narrower is defensible.
    y_lo, y_hi = min(lo_ii, hi_ii), max(lo_ii, hi_ii)

    twin = models.get(SONNET_45["price_twin"]) or {}
    price = twin.get("price1mBlended0To3To1")
    twin_cost = _cost(twin)
    if not isinstance(price, (int, float)) or not price or not twin_cost:
        raise ValueError("the price twin for Sonnet 4.5 lost its price or cost")
    q25, _med, q75 = _price_to_cost_ratio(models, non_reasoning=False)
    x = twin_cost                       # identical published price, same vendor
    x_lo, x_hi = price * q25, price * q75
    x_lo, x_hi = min(x_lo, x), max(x_hi, x)
    return Point(
        # GATEWAY, not BOTH: in the example configuration only the gateway serves it.
        label=SONNET_45["label"], group=GATEWAY, tier=OUR_ESTIMATE,
        x=x, y=y, x_lo=x_lo, x_hi=x_hi, y_lo=y_lo, y_hi=y_hi,
        basis=(f"absent from AA. Index interpolated from LMArena Elo {elo:.0f}, "
               f"bracketed by anchors at {lo_elo:.0f} and {hi_elo:.0f} index "
               f"{lo_ii:.1f}-{hi_ii:.1f}. Cost from the price it shares with "
               f"{SONNET_45['price_twin']}"),
        aa_name=None)


def load_fleet(models: dict | None = None, arena: dict | None = None,
               throughput: dict | None = None) -> list[Point]:
    """The models we can actually reach, positioned and tiered."""
    models = models if models is not None else _load(AA_COST)["models"]
    arena = arena if arena is not None else _load(LMARENA)["models"]
    tp = throughput if throughput is not None else _load(THROUGHPUT)["installed"]

    pts: list[Point] = []

    # --- paid endpoints: AA gives x and y directly when it ran them
    for group, fleet in ((GATEWAY, GATEWAY_FLEET), (BOTH, BOTH_FLEET),
                         (OUTSIDE, OUTSIDE_FLEET + gpt_fleet(models))):
        for label, aa_name in fleet:
            if aa_name is None:
                continue                                  # handled separately
            rec = models.get(aa_name)
            if rec is None:
                raise KeyError(
                    f"{label!r} expects AA row {aa_name!r}, which is not in the "
                    "corpus. Either AA renamed it or the fleet spec is stale -- "
                    "do not silently drop a model we can reach.")
            y = float(rec["intelligenceIndex"])
            cost = _cost(rec)
            if cost and not rec.get("intelligenceIndexIsEstimated"):
                t = _secs(rec)
                pts.append(Point(label=label, group=group, tier=MEASURED,
                                 x=cost, y=y, x_lo=cost, x_hi=cost,
                                 y_lo=y, y_hi=y, basis="AA measured both axes",
                                 aa_name=aa_name,
                                 secs=t, secs_lo=t, secs_hi=t))
                continue
            # AA prices it but never ran it: derive cost, keep its own y flag.
            price = rec.get("price1mBlended0To3To1")
            if not isinstance(price, (int, float)) or price <= 0:
                raise ValueError(
                    f"{label!r} has neither a measured cost nor a published "
                    "price; there is no honest way to place it on the x axis")
            q25, med, q75 = _price_to_cost_ratio(models, non_reasoning=True)
            pts.append(Point(
                label=label, group=group, tier=AA_ESTIMATED,
                x=price * med, y=y, x_lo=price * q25, x_hi=price * q75,
                y_lo=y, y_hi=y,
                basis=("index is AA's own estimate; AA publishes no cost, so cost "
                       f"= published ${price:.3f}/Mtok x the tokens-per-task "
                       "ratio of comparable non-reasoning models"),
                aa_name=aa_name, secs=_secs(rec), secs_lo=_secs(rec),
                secs_hi=_secs(rec)))

    pts.append(_estimate_sonnet_45(models, arena))

    # --- local: y from AA in the mode we route, x from electricity
    for label, aa_name, precision in LOCAL_FLEET:
        rec = models.get(aa_name)
        if rec is None:
            raise KeyError(f"{label!r} expects AA row {aa_name!r}, absent from "
                           "the corpus")
        row = tp.get(label)
        if not isinstance(row, dict) or not row.get("warm_tok_per_s"):
            raise KeyError(
                f"{label!r} has no measured warm_tok_per_s in "
                "routing/throughput.json; its cost would be unbounded")
        y = float(rec["intelligenceIndex"])
        tokens = _tokens_per_task(models, prefer=(aa_name,))
        lo, mid, hi = _local_cost_usd(tokens, float(row["warm_tok_per_s"]))
        tlo, tmid, thi = local_seconds(tokens, float(row["warm_tok_per_s"]))
        cut = QUANT_HAIRCUT.get(precision, 0.0)
        y_cut = y * (1.0 - cut) if cut else None
        # The index is AA's estimate for most of these rows; only one was run.
        tier = AA_ESTIMATED if rec.get("intelligenceIndexIsEstimated") else MEASURED
        pts.append(Point(
            label=label, group=LOCAL, tier=tier,
            x=mid, y=y, x_lo=lo, x_hi=hi,
            y_lo=min(y, y_cut) if y_cut else y, y_hi=y,
            basis=(f"x is electricity + amortised hardware "
                   f"({row['warm_tok_per_s']} tok/s measured, "
                   f"{tokens:,.0f} output tokens/task, "
                   f"{POWER_DELTA_W[0]:.0f}-{POWER_DELTA_W[1]:.0f} W assumed)"
                   + (f". {precision}: index shown with a {cut:.0%} haircut"
                      if cut else f". {precision}: no haircut recorded")),
            aa_name=aa_name, y_haircut=y_cut,
            secs=tmid, secs_lo=tlo, secs_hi=thi))

    return pts


#: Effort levels in increasing order, as AA spells them. `None` for anything else
#: (notably "Non-reasoning", which is a mode rather than a rung).
_EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")


def _effort_rank(name: str) -> int | None:
    """Position of this row's effort setting on the ladder, or None if it is not
    an effort variant at all."""
    if " (" not in name:
        return None
    inside = name.partition(" (")[2].rstrip(")").lower()
    for i, word in enumerate(_EFFORT_ORDER):
        if re.search(rf"\b{word}\b", inside):
            return i
    return None


def load_ladders(fleet: Iterable[Point], models: dict | None = None
                 ) -> dict[str, list[Point]]:
    """Every effort setting of each model we own, keyed by the fleet label.

    WHY THIS EXISTS. An effort setting is one API parameter, not a different
    product: if we pay for Opus 5.5 at max effort we can also call it at high
    effort for a third of the price. Treating only the flagship as "ours" put two
    Opus 5.5 variants in the "frontier we lack" pile, which is simply false -- and
    it hid the largest saving available anywhere on the chart.

    Returns ONLY the siblings, flagship included, for models with more than one
    published effort row; a single-row model is omitted rather than given a
    one-point ladder. Local models are excluded: their effort ladder is not a
    purchasing decision and our own sweep measured thinking as harmful on the jobs
    we route.
    """
    models = models if models is not None else _load(AA_COST)["models"]
    out: dict[str, list[Point]] = {}
    for p in fleet:
        if p.group == LOCAL or not p.aa_name:
            continue
        base = p.aa_name.split(" (")[0]
        rungs: list[tuple[int, Point]] = []
        for name, rec in models.items():
            if name.split(" (")[0] != base:
                continue
            rank = _effort_rank(name)
            # A "Non-reasoning" row is a different MODE, not a rung on the effort
            # ladder, and it is not monotonic with the others -- including it drew a
            # sharp V through the GPT-6 Sol ladder, because non-reasoning costs more
            # than `low` while scoring far below it. A ladder that doubles back is
            # not a ladder.
            if rank is None:
                continue
            c = _cost(rec)
            if c is None or c <= 0 or rec.get("intelligenceIndexIsEstimated"):
                continue
            y = float(rec["intelligenceIndex"])
            t = _secs(rec)
            rungs.append((rank, Point(
                label=name, group=p.group, tier=MEASURED,
                x=c, y=y, x_lo=c, x_hi=c, y_lo=y, y_hi=y,
                basis="same model, different effort setting", aa_name=name,
                secs=t, secs_lo=t, secs_hi=t)))
        if len(rungs) > 1:
            # Ordered by EFFORT, not by cost: effort is the thing being varied, and
            # cost is merely its consequence.
            out[p.label] = [pt for _r, pt in sorted(rungs, key=lambda t: t[0])]
    return out


FRONTIER = "frontier"
WATCHED = "watched"

#: Vendors we do not have but want to keep an eye on. Named and labelled rather
#: than left anonymous in the background cloud, because "who is catching up" is a
#: question this chart is asked even though the answer changes no routing today.
#:
#: Gemini earns it despite being dominated on every plottable row -- eight of its
#: nine by a GPT tier already in hand. Watching is not the same as buying.
WATCHED_PATTERNS = (r"^Gemini\b",)


def watched(published: Iterable[Point], fleet: Iterable[Point],
            ladders: dict[str, list[Point]] | None = None) -> list[Point]:
    """Plottable rows from vendors we track but do not have.

    Excludes anything already drawn as ours, so a vendor that later appears in the
    fleet cannot be labelled twice. Returns them tagged WATCHED; the renderer keeps
    them grey and transparent -- they are context, not options.
    """
    ours = {p.aa_name for p in fleet if p.aa_name}
    for rungs in (ladders or {}).values():
        ours.update(r.aa_name for r in rungs if r.aa_name)
    out = []
    for p in published:
        if p.label in ours:
            continue
        if any(re.search(pat, p.label) for pat in WATCHED_PATTERNS):
            out.append(dataclasses.replace(p, group=WATCHED))
    return sorted(out, key=lambda p: -p.y)


def pareto(pts: Iterable[Point]) -> list[Point]:
    """Models no other model beats on BOTH axes -- cheaper AND smarter.

    Lives here rather than in the renderer so it is testable and so the chart and
    any prose about the chart cannot compute it two different ways.
    """
    pts = list(pts)
    out = [p for p in pts
           if not any(q.x < p.x * 0.999 and q.y > p.y + 1e-9 for q in pts)]
    return sorted(out, key=lambda p: p.x)


def frontier_not_ours(published: Iterable[Point], fleet: Iterable[Point],
                      ladders: dict[str, list[Point]] | None = None
                      ) -> list[Point]:
    """Frontier models we are NOT already showing, relabelled as their own group.

    These are the best score obtainable at each price anywhere in the field, so
    they are the standard our own fleet is judged against. Worth naming rather
    than leaving anonymous in the background cloud.

    CORRECTED. An earlier version keyed on the flagship row alone, so every effort
    variant of a model we own counted as "not ours" -- 13 of 15 supposed gaps were
    actually reachable, including two Opus 5.5 settings and the whole GPT-6 family.
    Passing `ladders` folds those back in, and what remains is genuinely absent.
    """
    ours = {p.aa_name for p in fleet if p.aa_name}
    for rungs in (ladders or {}).values():
        ours.update(r.aa_name for r in rungs if r.aa_name)
    return [dataclasses.replace(p, group=FRONTIER)
            for p in pareto(published) if p.label not in ours]


def fleet_summary(pts: Iterable[Point]) -> dict:
    """Counts the captions are computed FROM, never hardcoded beside.

    Two generated captions in this repo drifted into being false because nothing
    recomputed them. Any sentence stating a number about this chart takes it from
    here.
    """
    pts = list(pts)
    by_group = {g: [p for p in pts if p.group == g] for g in GROUPS}
    by_tier = {t: [p for p in pts if p.tier == t] for t in TIERS}
    paid = [p for p in pts if p.group in (GATEWAY, OUTSIDE)]
    local = by_group[LOCAL]
    # Separated on purpose. `cheapest_paid` currently lands on Nova Micro at a
    # price AA never billed -- a DERIVED figure with a 7x band. A caption saying
    # "the cheapest thing you can pay for" must quote the measured one, or it
    # states an estimate as a fact.
    paid_measured = [p for p in paid if not p.has_x_range]
    return {
        "n_fleet": len(pts),
        "n_by_group": {g: len(v) for g, v in by_group.items()},
        "n_by_tier": {t: len(v) for t, v in by_tier.items()},
        "n_haircut_pairs": sum(1 for p in pts if p.y_haircut is not None),
        "cheapest_paid": min((p.x for p in paid), default=None),
        "cheapest_paid_measured": min((p.x for p in paid_measured), default=None),
        "cheapest_paid_measured_label": min(
            paid_measured, key=lambda p: p.x).label if paid_measured else None,
        "dearest_paid": max((p.x for p in paid), default=None),
        "local_cost_lo": min((p.x_lo for p in local), default=None),
        "local_cost_hi": max((p.x_hi for p in local), default=None),
        "best_local_y": max((p.y for p in local), default=None),
        "best_paid_y": max((p.y for p in paid), default=None),
    }
