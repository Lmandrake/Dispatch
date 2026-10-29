"""The seed: what published evidence says about each destination, before any use.

Pure. No network, no live server, no committed-result reads. Everything here comes
from `references/` plus our own measured `routing/throughput.json`, so it runs from
Cowork, from a launchd job, and inside a hook's cold path.

🔴 THREE DESTINATION KINDS, AND THEY ARE NOT RANKED AGAINST EACH OTHER.

  * `local`      -- oMLX on this machine. `refer` gives a per-job TIER and SCORE from
    published per-skill benchmarks, and `routing/throughput.json` gives a MEASURED
    generation rate. This is the only set with comparable per-job evidence, so it is
    the only set that gets ranked.
  * `sanctioned` -- the Anthropic models the enterprise gateway serves. We have an
    intelligence index and a cost per task for these, and **no per-skill coverage at
    all**: `references/artificial-analysis.json`, which is what `refer` reads, holds
    ZERO Anthropic rows. So there is no tier to compute and none is invented.
  * `consult`    -- ChatGPT, Jev, an internal endpoint. **No corpus anywhere carries cost,
    quality, latency or reachability for the first two.** Their prior is UNKNOWN on
    day one and the ledger is the only thing that will ever give them one.

🔴 WHY THE KINDS ARE NOT POOLED INTO ONE RANKING. Because ranking them would repeat,
one level up, the error the cold design review caught one level down (finding T3): a
`refer` tier and an intelligence index are unlike quantities, and nothing defines how
a 27B local model at DELEGATE compares to Opus 5 with no per-skill figure. A combined
list would have to invent that comparison, and the invented answer is worse than two
honest lists -- it would put a 27B above Opus on "hand-off clearance" and read as a
measurement. So `bin/delegate` ranks the local set and reports the sanctioned set as
the escalation path, priced.

🔴 A THROUGHPUT NUMBER IS NOT A DURATION PREDICTION (review finding S4).
`routing/throughput.json` is ONE short, warm prompt: ~120 tokens in, 250 out, n=3, on
a deterministic server. A real task has a long input, a possible cold load, and
queueing. So `secs_for` requires an explicit output-token assumption and says what it
assumed; `predicted_secs` is None when nobody supplied one. Inventing a duration from
a generation rate is how a time budget becomes a false promise.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

from dispatchlib.omlx import OMLX_REPO, harness

REPO = pathlib.Path(__file__).resolve().parents[1]
#: Measured throughput and the AA cost corpus are the oMLX destination's own evidence,
#: kept in `providers/omlx/` and read from there.
THROUGHPUT_PATH = OMLX_REPO / "routing" / "throughput.json"
AA_COST_PATH = OMLX_REPO / "references" / "artificial-analysis-cost.json"

LOCAL = "local"
SANCTIONED = "sanctioned"
CONSULT = "consult"

#: 🔴 THE FOUR GAPS THE SEED CANNOT CLOSE. Declared so a caller reports them as
#: unknown instead of filling them in. Each is attached to the priors it affects, so
#: a route's `unknowns` list is derived from this table rather than retyped.
GAPS = {
    "no_task_size_model": (
        "Nothing here relates a task's input size to a duration or a cost. The "
        "throughput figure is one short prompt; the AA cost figure is one task of "
        "AA's own shape. A route for a 40k-token input is extrapolating."),
    "no_rate_limits": (
        "No source anywhere -- published or ours -- carries a rate limit, a quota, "
        "or a concurrency ceiling for any destination. A route cannot tell you "
        "whether the fifth parallel job will be served."),
    "no_quantisation_figures": (
        "No published source measures the quantisation we actually serve: AA has "
        "zero matches for any precision keyword across its whole corpus. `refer`'s "
        "haircut is literature-derived, never measured, so the accuracy half of "
        "every local verdict is an assumption."),
    "no_corpus_for_two_consults": (
        "ChatGPT and Jev have zero representation in any corpus -- no cost, no "
        "quality, no latency, no reachability. Their prior is UNKNOWN and only the "
        "disposition ledger will ever change that."),
    "effort_is_unspecified": (
        "AA publishes one row per reasoning-effort level and our requests set no "
        "effort at all, so there is no single row that describes what we would get. "
        "The spread across the published efforts is reported instead of one row "
        "being chosen."),
}

#: Gateway model id SUFFIX (everything after the account's region prefix, e.g.
#: `us-gov.` or `us.`) -> the family name AA publishes it under. DECLARED, because
#: AA's own naming is inconsistent across generations -- `Claude 4.5 Sonnet` for the
#: older model and `Claude Sonnet 5` for the newer -- so a derived mapping would
#: silently miss.
#:
#: The REGION PREFIX is never written here -- it names an account, and
#: `gateway_family_for()` matches a real wire id by SUFFIX so the same table works
#: under whichever account is active without reading which one that is.
#: Account comes from the environment, never named here: see
#: a sibling tool's environment helper
#:
#: Load-balanced aliases (`-lb-1`, `-load-balanced`) are deliberately absent: they are
#: the same weights behind a different route and would triple every list.
GATEWAY_FAMILY_SUFFIXES = {
    "anthropic.claude-opus-5": "Claude Opus 5",
    "anthropic.claude-sonnet-5": "Claude Sonnet 5",
    "anthropic.claude-opus-4-8": "Claude Opus 4.8",
    "anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude 4.5 Sonnet",
}


def gateway_family_for(gid: str) -> str | None:
    """The AA family name for a real wire id, matched by SUFFIX -- never by a
    hardcoded region prefix, so this resolves the same way regardless of which
    account's prefix the gateway puts in front of `anthropic.*`."""
    return next((name for suffix, name in GATEWAY_FAMILY_SUFFIXES.items()
                if gid.endswith(suffix)), None)

def _consults() -> dict:
    """The by-name destinations and what each is for, from `routing/destinations.json`.
    Read from the registry so this cannot become a second list of them."""
    reg = json.loads((REPO / "routing" / "destinations.json").read_text())
    return {k: v["for"] for k, v in reg["destinations"].items()}


#: The by-name destinations, and what each one is for. They dispatch by name, never
#: by rank -- see the module docstring.
CONSULTS = _consults()


@dataclasses.dataclass(frozen=True)
class DestinationPrior:
    """What published evidence says about one destination for one job kind.

    Every numeric field is `None` when no source carries it. `0` would claim a
    measurement; `None` claims nothing, and `unknowns` says which gap applies.
    """
    destination: str
    kind: str
    task_kind: str | None = None
    tier: str = "UNKNOWN"
    score: float | None = None
    weakest_skill: str | None = None
    #: Correspondence quality for a local alias: measured / proxy / estimated.
    alias_basis: str | None = None
    #: Intelligence index, where a source publishes one. For a sanctioned family this
    #: is an INTERVAL across published efforts, not a point.
    index_lo: float | None = None
    index_hi: float | None = None
    usd_lo: float | None = None
    usd_hi: float | None = None
    #: Published END-TO-END seconds per AA task. Not a prediction for our tasks.
    published_secs_lo: float | None = None
    published_secs_hi: float | None = None
    #: Published blended price per 1M tokens, where a source carries one. This is what
    #: makes a sanctioned route comparable to a local one AT THE SAME TASK SIZE --
    #: `usd_lo/hi` above is per AA *index task*, which is ~27k output tokens for
    #: Sonnet 5 and therefore ~68x a 400-token job. Printing the two per-task figures
    #: side by side reads as "local is 100x cheaper" when the tasks differ by 68x in
    #: length, which is the incomparability this whole module exists to refuse.
    price_1m_lo: float | None = None
    price_1m_hi: float | None = None
    #: MEASURED warm generation rate, short prompts only.
    tok_per_s: float | None = None
    cold_load_s: float | None = None
    weight_gb: float | None = None
    #: What the evidence is ABOUT, so a cell cannot survive its subject being
    #: replaced (review finding A2).
    config_fingerprint: str | None = None
    unknowns: tuple[str, ...] = ()
    note: str | None = None

    def usd_for(self, output_tokens: int) -> dict | None:
        """What this local route actually costs, as an interval, or None.

        🔴 LOCAL IS NOT FREE, AND ELECTRICITY IS THE SMALL HALF. `costmap` prices a
        local task as power PLUS amortised hardware, because the machine is ~18x the
        power: $0.457/h at $3,999 over 3 years at 8 h/day. Electricity alone put a 27B
        task at $0.013 and made local look 4-6x cheaper than anything purchasable;
        adding the machine moved it to $0.25-$0.78 and REVERSED the conclusion. The
        arithmetic was right all along and the BASIS was wrong, which is the harder
        error to see.

        This exists because `route` prints the gateway at a real dollar figure, and
        printing nothing beside it reads as "free" -- which is the same error with the
        decimal point moved all the way.

        🔴 THE DUTY CYCLE IS THE LOAD-BEARING GUESS, not a measurement: 24 h/day cuts
        the hardware term threefold. It is named in the returned `basis` so a reader
        can argue with it rather than inherit it.
        """
        if self.kind == SANCTIONED:
            if self.price_1m_lo is None:
                return None
            # A BLENDED price, so this mixes input and output tokens at AA's own
            # 3:1 assumption. Named as an approximation because it is one: a job
            # with a huge prompt and a short answer sits at the wrong end of that
            # blend. It is still the comparable figure; `usd_lo/hi` is not.
            return {"lo": self.price_1m_lo * output_tokens / 1e6,
                    "mid": None,
                    "hi": self.price_1m_hi * output_tokens / 1e6,
                    "assumed_output_tokens": output_tokens,
                    "basis": (f"published blended price "
                              f"${self.price_1m_lo:g}-{self.price_1m_hi:g}/1M tokens "
                              f"across effort levels, applied to the output count. "
                              f"Blended 3:1 input:output by AA, so a prompt-heavy job "
                              f"costs more than this")}
        if not self.tok_per_s:
            return None
        costmap = harness("costmap")
        MACHINE_DUTY_HOURS_PER_DAY = costmap.MACHINE_DUTY_HOURS_PER_DAY
        MACHINE_LIFE_YEARS = costmap.MACHINE_LIFE_YEARS
        MACHINE_PRICE_USD = costmap.MACHINE_PRICE_USD
        _local_cost_usd = costmap._local_cost_usd
        lo, mid, hi = _local_cost_usd(output_tokens, self.tok_per_s)
        return {"lo": lo, "mid": mid, "hi": hi,
                "assumed_output_tokens": output_tokens,
                "basis": (f"power plus hardware amortised at ${MACHINE_PRICE_USD:,.0f} "
                          f"over {MACHINE_LIFE_YEARS:g}yr at "
                          f"{MACHINE_DUTY_HOURS_PER_DAY:g}h/day -- the duty cycle is a "
                          f"guess, and 24h/day would cut the hardware term threefold")}

    def secs_for(self, output_tokens: int) -> dict | None:
        """A duration ESTIMATE for a given output length, with its assumptions named.

        Returns None when there is no measured rate. Never folds the cold load in
        silently: `warm` and `cold` are separate, because an 8-second model load is
        the difference between a 4-second job and a 12-second one and a caller with a
        6-second budget needs to know which it is getting.

        🔴 This is an estimate of GENERATION time for a SHORT prompt. It does not
        model prompt processing, queueing, or contention, and for the long-context
        jobs prompt processing dominates. See `GAPS['no_task_size_model']`.
        """
        if not self.tok_per_s:
            return None
        warm = output_tokens / self.tok_per_s
        return {"warm_secs": round(warm, 1),
                "cold_secs": round(warm + (self.cold_load_s or 0.0), 1),
                "assumed_output_tokens": output_tokens,
                "basis": "measured warm generation rate on one short pinned prompt; "
                         "excludes prompt processing, queueing and contention"}


def _throughput() -> dict:
    try:
        return json.loads(THROUGHPUT_PATH.read_text()).get("installed") or {}
    except Exception:                                   # noqa: BLE001
        return {}


def _aa_cost() -> dict:
    try:
        return json.loads(AA_COST_PATH.read_text()).get("models") or {}
    except Exception:                                   # noqa: BLE001
        return {}


def _fingerprint(model: str, extra: dict | None = None) -> str:
    """A short, stable id for *what the evidence is about*.

    Review finding A2: swap a 4-bit build in under the same served name and a
    favourable empirical cell keeps applying to a different artifact. The weight size
    is included because it is the cheapest thing that actually changes when the
    artifact does -- a re-quantised build of the same name has a different file size.
    """
    import hashlib
    body = json.dumps({"model": model, **(extra or {})}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ local fleet --

def local_priors(task_kind: str, served: list[str], corpus=None
                 ) -> list[DestinationPrior]:
    """One prior per served local model, for one job kind.

    `served` is the fleet oMLX actually answered with -- never an alias dict. An
    alias is not an inventory: `refer.ALIASES` went on recommending two models for
    two days after they were deleted from this disk.
    """
    refer, router = harness("refer"), harness("router")
    corpus = corpus if corpus is not None else refer.Corpus()
    tput = _throughput()
    aliased = [m for m in served
               if m in refer.ALIASES and m not in router.REMOTE_ALIASES]
    out = []
    for m in aliased:
        a = refer.assess(m, task_kind, corpus)
        skills = [s for s in a["skills"] if s.get("pctile") is not None]
        weakest = min(skills, key=lambda s: s["pctile"], default=None)
        t = tput.get(m) or {}
        gaps = ["no_task_size_model", "no_rate_limits"]
        if a.get("precision"):
            gaps.append("no_quantisation_figures")
        out.append(DestinationPrior(
            destination="omlx/" + m, kind=LOCAL, task_kind=task_kind,
            tier=a["tier"], score=a["score"],
            weakest_skill=weakest["skill"] if weakest else None,
            alias_basis=a["alias_basis"],
            tok_per_s=t.get("warm_tok_per_s"), cold_load_s=t.get("cold_load_s"),
            weight_gb=t.get("gb"),
            config_fingerprint=_fingerprint(m, {"gb": t.get("gb"),
                                                "precision": a.get("precision")}),
            unknowns=tuple(gaps),
            note=None if t else "no measured throughput for this model"))
    return out


# -------------------------------------------------------------- the gateway path --

def sanctioned_priors(served: list[str]) -> list[DestinationPrior]:
    """One prior per sanctioned FAMILY the gateway serves.

    🔴 NO TIER, EVER. `references/artificial-analysis.json` -- the corpus `refer`
    reads for per-skill percentiles -- holds zero Anthropic rows, so there is no
    per-skill figure for any of these and nothing to compute a job tier from. The
    index and the cost come from `artificial-analysis-cost.json`, which is a second
    AA corpus carried for exactly this reason.

    🔴 INTERVALS, NOT POINTS, across reasoning effort. AA publishes a row per effort
    level; our requests set no effort, so no single row describes what we would get.
    Reporting the spread is the honest form and reporting one row would be a choice
    masquerading as a reading -- the same error as scoring a candidate in a mode we
    do not serve, which this repo has already made once.
    """
    cost = _aa_cost()
    out = []
    for gid in served:
        family = gateway_family_for(gid)
        if not family:
            continue
        rows = [r for name, r in cost.items() if _is_family(name, family)]
        if not rows:
            out.append(DestinationPrior(
                destination="sanctioned/" + gid, kind=SANCTIONED,
                unknowns=("no_corpus_for_two_consults",),
                note=f"no published figure for {family!r} in the cost corpus"))
            continue
        idx = [r["intelligenceIndex"] for r in rows if r.get("intelligenceIndex")]
        usd = [r["costPerTask"] for r in rows if r.get("costPerTask")]
        secs = [r["secondsPerTask"] for r in rows if r.get("secondsPerTask")]
        # The per-1M blended price is the ONLY field here that makes a sanctioned
        # route comparable to a local one at the same task size. `costPerTask` is per
        # AA index task and those tasks are enormous.
        p1m = [r["price1mBlended0To3To1"] for r in rows
               if r.get("price1mBlended0To3To1")]
        out.append(DestinationPrior(
            destination="sanctioned/" + gid, kind=SANCTIONED,
            tier="UNKNOWN",
            index_lo=min(idx) if idx else None, index_hi=max(idx) if idx else None,
            usd_lo=min(usd) if usd else None, usd_hi=max(usd) if usd else None,
            published_secs_lo=min(secs) if secs else None,
            published_secs_hi=max(secs) if secs else None,
            price_1m_lo=min(p1m) if p1m else None,
            price_1m_hi=max(p1m) if p1m else None,
            config_fingerprint=_fingerprint(gid, {"family": family}),
            unknowns=("effort_is_unspecified", "no_task_size_model",
                      "no_rate_limits"),
            note=f"{family}: {len(rows)} published effort rows; no per-skill "
                 f"coverage exists, so no job tier"))
    return out


def _is_family(published_name: str, family: str) -> bool:
    """Does an AA row belong to this family?

    Prefix match on the family name followed by ` (` or end-of-string, so
    `Claude Opus 5` does NOT swallow `Claude Opus 5.5`. That is not hypothetical --
    the two are adjacent in the corpus and a bare `startswith` joins them, which
    would quietly widen every Opus 5 interval with a different model's numbers.
    """
    return published_name == family or published_name.startswith(family + " (")


# ------------------------------------------------------------------- consults --

def consult_priors() -> list[DestinationPrior]:
    """One prior per consult destination. All UNKNOWN, by measurement of the corpus.

    Two of the three genuinely have no representation anywhere; the internal endpoint has an
    endpoint and a key but its models are not in any published corpus under names we
    can resolve. So all three carry `no_corpus_for_two_consults` and no numbers.
    These dispatch by NAME -- a caller asks for a consult -- and never by rank.
    """
    return [DestinationPrior(destination="consult/" + k, kind=CONSULT,
                             unknowns=("no_corpus_for_two_consults",), note=v)
            for k, v in CONSULTS.items()]


def unknowns_text(keys) -> list[str]:
    """Spell out a prior's `unknowns`, derived from `GAPS` rather than retyped.

    CLAUDE.md: prose that states a fact about the data must be computed from the
    data. A hand-typed gap list drifts the moment a gap closes.
    """
    return [GAPS[k] for k in keys if k in GAPS]
