"""Routing / consumption layer -- the hand-off this whole instrument was built toward.

Everything upstream decides WHICH model is trustworthy for WHICH job. This module is
what a caller actually invokes to (a) get that recommendation and (b) optionally
dispatch the job to the chosen local model and hand its output back.

🔴 TWO RECOMMENDERS, AND THE DEFAULT IS THE PUBLISHED ONE.

  * `recommend_published()` -- THE DEFAULT. Ranks the models oMLX is actually serving
    using `refer`, i.e. PUBLISHED benchmarks. This is what `bin/route` shows and
    dispatches from. Read its section comment for why, and for the two guarantees the
    other path cannot give (candidates are the served fleet; dispatch refuses an
    unserved model).

  * `recommend()` -- the RETIRED path. Reads `routing/routing-table.json`, our own
    archived sweep evidence, which the project ruled out of use on 2026-10-01. Kept
    importable because the archived corpus is still legitimately read by
    `scorecard.py` / `table.py` / `loose.py` / `roster.py`, and reachable from the
    CLI only behind an explicit opt-in flag that says what it reads.

Everything from here down to the published section describes the retired path. Its
rules are preserved verbatim rather than deleted, because the archived numbers are
still consumed and they have to keep being read the way they were written.

Two design rules, both learned expensively upstream and preserved here on purpose:

  * Reliability, not economics, sets the trust tier. A local run is free, so the
    table's economic `delegable` flag is carried as context but NEVER used to gate --
    a "any fabrication disqualifies" cliff has been written and reverted three times,
    and it refuses the entire fleet including models at a perfect pass rate. The tier
    a caller sees is a transparent function of measured reliability only.

  * A run that did not return is not a success. Effective success folds the void rate
    in: eff = pass_rate * (1 - void_rate). A model that answers 58% of the time and is
    silent the other 14% is not "0.58 good", it is ~0.50 good, and is tiered as such.

  * Thin evidence cannot earn full trust. A cell flagged `indicative_only` (too few
    graded trials) is capped at VERIFY no matter how clean it looks.

Mode default is `nothink`: turning on the local models' thinking mode was measured to
not help and often to hurt (the 27B-8bit model dropped from 80% to 17% on the
garbled-names job), so plain mode is the recommended local mode.

Pure stdlib. The recommendation half needs only the table -- no server, no results
dir -- so it runs anywhere, including inside Cowork. Dispatch needs a live oMLX server
and is guarded behind the egress gate; it never stores prompt or output text.
"""

from __future__ import annotations

import json
import pathlib

DEFAULT_TABLE_PATH = pathlib.Path(__file__).resolve().parents[2] / "routing" / "routing-table.json"

# Trust tiers, best first. A caller ranks candidate cells by this order, then by
# effective success, then by throughput.
DELEGATE = "DELEGATE"
VERIFY = "VERIFY"
DO_NOT = "DO NOT"
UNKNOWN = "UNKNOWN"
_TIER_RANK = {DELEGATE: 3, VERIFY: 2, DO_NOT: 1, UNKNOWN: 0}

# Reliability thresholds on effective success. Chosen so the tiers reproduce the
# human-read n=20 grid exactly; pinned by test_router. No separate void guard: eff
# already folds the void rate in (eff = pass*(1-void)), so with pass <= 1.0 any void
# above 0.05 has already pulled eff below the DELEGATE line -- a void guard here would
# be redundant, never independently firing, exactly the kind of untested guard CLAUDE.md
# warns against.
_DELEGATE_MIN = 0.95
_VERIFY_MIN = 0.70


def load_table(path: pathlib.Path | str = DEFAULT_TABLE_PATH) -> dict:
    return json.loads(pathlib.Path(path).read_text())


def headline(row: dict) -> tuple[float | None, str]:
    """The pass rate a tier may be computed from, and which basis it came from.

    `atoms` means the cell was re-derived from its stored per-trial atom vectors:
    recall AND traps AND structure. `legacy` means the only number available is the
    recall-only keyword rate, which an echo of the fixture's own input gets through
    on 7 of 8 jobs (tools/echo_audit.py) -- so it cannot distinguish a model that
    did the work from one that parroted the input.

    An absent `headline_basis` reads as `legacy`, fail-closed: a table generated
    before the atoms basis existed must not be treated as though it had been
    re-derived. That is the same direction every other unknown in this module
    takes.
    """
    basis = row.get("headline_basis") or "legacy"
    if basis == "atoms":
        return row.get("pass_rate_atoms"), "atoms"
    return row.get("pass_rate"), "legacy"


def eff_success(row: dict) -> float | None:
    """The headline rate discounted by the fraction of runs that never returned.
    None when the cell was never measured (no rate on the basis in force)."""
    pr, _ = headline(row)
    if pr is None:
        return None
    void = row.get("void_rate") or 0.0
    return pr * (1.0 - void)


def tier(row: dict) -> str:
    """Trust tier for one measured cell, from reliability alone."""
    eff = eff_success(row)
    if eff is None:
        return UNKNOWN
    if eff < _VERIFY_MIN:
        return DO_NOT
    # Weak evidence cannot earn full trust, for the same reason thin evidence
    # cannot: a legacy-only cell scored 1.00 might be a model doing the job
    # perfectly or a model echoing its input, and the number cannot tell them
    # apart. A2's 30B is the worked example -- 1.00 on the legacy basis, 0.00 on
    # the atom basis, with one trap and one structure atom failing all 20 trials.
    # And a fixture whose own input passes its own grading cannot hand anything
    # over at all: a 1.00 there is a score a copy-paste would have earned. `is
    # True` on purpose -- None means the check could not run (nothing to echo),
    # which must not demote the cell.
    _, basis = headline(row)
    if (eff >= _DELEGATE_MIN and not row.get("indicative_only")
            and basis == "atoms" and row.get("echo_permeable") is not True):
        return DELEGATE
    return VERIFY


def _candidates(table: dict, activity: str, mode: str, egress: str) -> list[dict]:
    act = table.get("activities", {}).get(activity)
    if not act:
        return []
    return [r for r in act.get("ranked", [])
            if r.get("mode") == mode and r.get("egress") == egress]


def _sort_key(row: dict):
    # best tier, then most reliable, then fastest, then fewest tokens burned.
    return (_TIER_RANK[tier(row)],
            eff_success(row) or 0.0,
            row.get("tok_per_s_p50") or 0.0,
            -(row.get("max_tokens_effective") or 0))


def recommend(table: dict, activity: str, mode: str = "nothink",
              egress: str = "local") -> dict:
    """Pick the model a job should go to. Returns a plain dict describing the choice,
    the tier, the numbers behind it, and the runners-up. model_ref is None when no
    measured local option clears even the VERIFY bar (or none was measured at all)."""
    cands = _candidates(table, activity, mode, egress)
    kind = table.get("activities", {}).get(activity, {}).get("kind")
    if not cands:
        return {"activity": activity, "mode": mode, "kind": kind, "egress": egress,
                "model_ref": None, "tier": UNKNOWN, "eff_success": None,
                "n_trials": 0, "pass_rate": None, "pass_rate_atoms": None,
                "headline_basis": None, "void_rate": None,
                "delegable_econ": None, "alternatives": [],
                "reason": f"no {egress} measurement for {activity} in {mode} mode"}

    ranked = sorted(cands, key=_sort_key, reverse=True)
    best = ranked[0]
    best_tier = tier(best)
    chosen = best if best_tier in (DELEGATE, VERIFY) else None

    def _brief(r):
        return {"model_ref": r.get("model_ref"), "tier": tier(r),
                "eff_success": eff_success(r), "pass_rate": r.get("pass_rate"),
                "headline_basis": headline(r)[1],
                "void_rate": r.get("void_rate"), "n_trials": r.get("n_trials")}

    return {
        "activity": activity, "mode": mode, "kind": kind, "egress": egress,
        "model_ref": (chosen or best).get("model_ref") if chosen else None,
        "best_available": best.get("model_ref"),
        "tier": best_tier,
        "eff_success": eff_success(best),
        "n_trials": best.get("n_trials"),
        "pass_rate": best.get("pass_rate"),
        "pass_rate_atoms": best.get("pass_rate_atoms"),
        "headline_basis": headline(best)[1],
        "void_rate": best.get("void_rate"),
        "delegable_econ": best.get("delegable"),
        "alternatives": [_brief(r) for r in ranked[1:4]],
        "reason": _reason(best, best_tier),
    }


def _reason(row: dict, t: str) -> str:
    eff = eff_success(row)
    pct = None if eff is None else round(eff * 100)
    n = row.get("n_trials")
    basis = headline(row)[1]
    if t == DELEGATE:
        # Safe to say on the atom basis only, which is the only basis that can reach
        # DELEGATE: a fired trap or a blown structure budget scores the run as
        # not-passed, so a ~100% rate here means neither happened on those runs.
        return f"completed the job on ~{pct}% of {n} test runs -- safe to hand off"
    if t == VERIFY:
        if row.get("echo_permeable") is True and eff is not None and eff >= _DELEGATE_MIN:
            return (f"scored ~{pct}% of {n} runs, but a copy of the input scores the "
                    f"same on this job -- the test cannot tell doing the work from "
                    f"repeating the question, so check the result")
        if basis != "atoms" and eff is not None and eff >= _DELEGATE_MIN:
            return (f"scored ~{pct}% of {n} runs, but only on keyword matching -- a "
                    f"basis an echo of the input gets through, so check the result "
                    f"until this job is re-scored on the stricter checks")
        v = row.get("void_rate") or 0.0
        extra = f", and was silent on {round(v*100)}% of runs" if v > 0.02 else ""
        return f"got it right ~{pct}% of {n} runs{extra} -- usable, but check the result"
    if t == DO_NOT:
        return f"the best local option only managed ~{pct}% over {n} runs -- do not delegate this locally"
    return "not measured"


def explain(rec: dict) -> str:
    """One human sentence for a routing decision. No jargon, no stats symbols.

    When the candidate set could not be verified against the live server, the note
    is appended HERE rather than left for the CLI to remember, so that every caller
    that prints a decision prints the caveat with it. The brief for this path was
    explicit: never silently pretend the fallback set is the installed set.
    """
    act = rec["activity"]
    if rec["tier"] == DELEGATE:
        base = f"Hand {act} to {rec['model_ref']} — {rec['reason']}."
    elif rec["tier"] == VERIFY:
        base = f"Hand {act} to {rec['model_ref']}, then check it — {rec['reason']}."
    elif rec["tier"] == DO_NOT:
        base = (f"Keep {act} in-house — {rec['reason']}. "
                f"(Best local was {rec['best_available']}.)")
    else:
        base = f"No verdict for {act}: {rec['reason']}."
    if rec.get("served_known") is False:
        base += _UNVERIFIED_FLEET_NOTE
    return base


# --------------------------------------------------------------------------------
# The published-figures recommender -- the DEFAULT path, and the one `bin/route`
# dispatches from.
# --------------------------------------------------------------------------------
#
# WHY THIS EXISTS. `recommend()` above reads `routing/routing-table.json`, which is
# our own RETIRED sweep evidence. The project ruling (2026-10-01) is to use
# published figures only. Measured the same day over all ten job kinds against the five models
# oMLX actually serves, the table path was wrong on seven of them: it recommended
# `Qwen3.8-27B-OBLITERATED-OptiQ-4bit` at DELEGATE for A2/A3/E3/F1/F2 where published
# evidence rates it DO NOT at the 28th percentile, and recommended
# `Qwen3-30B-A3B-Instruct-2507-4bit` -- deleted from this disk on 2026-09-29 -- for
# A3/E4/F1. So the recommendation now comes from `refer`, and dispatch is unchanged.
#
# TWO RULES THIS PATH ADDS, both of which the table path could not enforce:
#
#   * THE CANDIDATE SET IS THE SERVED FLEET, not an alias dict. An alias is not an
#     inventory: `refer.ALIASES` went on recommending two models for two days after
#     they were deleted, because nothing in that module reads the server. Candidates
#     are what `GET /v1/models` answers, intersected with the aliases -- so a model
#     that is gone cannot be recommended, and a model that is present but unaliased
#     cannot be recommended either (we would have no published figure for it).
#
#   * DISPATCH REFUSES AN UNSERVED MODEL, and `--force` does not lift that. Forcing a
#     DO-NOT tier is a judgement a caller is entitled to make; dispatching to a model
#     that is not loaded is never a judgement, it is a 404 with a confusing message.
#
# WHAT IS DELIBERATELY ABSENT. Every field that only means something for our own
# sweeps -- n_trials, pass_rate, pass_rate_atoms, eff_success, void_rate,
# headline_basis, delegable_econ -- is None here, not 0 and not a midpoint. `0` must
# mean a measured zero; this path measured nothing, it cited someone else.

#: The oMLX OpenAPI base. `/models` hangs off it.
OMLX_V1 = "http://127.0.0.1:8000/v1"

#: Token budgets for the published path. Same two numbers `routing-table.json`
#: carries under `defaults.max_tokens`, restated here so this path never has to open
#: the retired table to dispatch.
DEFAULT_MAX_TOKENS = {"nothink": 6000, "think": 12000}

#: Aliases in `refer.ALIASES` that are NOT on this disk: models on a remote
#: enterprise endpoint. They must never enter a LOCAL-egress candidate set, and the
#: exclusion has to be declared rather than derived, because the only thing that
#: records which aliases are remote is `refer.ALIASES`'s own section comment and
#: `routing/roster.json`, which is gitignored.
#:
#: An allowlist is a CLAIM, so there is a reverse guard: a stale or mistyped entry
#: here is inert in the dangerous direction (it would let a remote model through as
#: local), and `test_every_declared_remote_alias_is_a_real_alias` fails on one.
REMOTE_ALIASES = frozenset({"remote-gemma-31b-128k"})

#: Evidence-quality order, used only to break a score tie deterministically.
_BASIS_RANK = {"measured": 3, "proxy": 2, "estimated": 1, "direct": 0}

_UNVERIFIED_FLEET_NOTE = (
    " (CANDIDATE SET UNVERIFIED: the local server did not answer, so this ranks "
    "every model we hold a published alias for, which is not the same as the "
    "models actually loaded.)")


def _refer():
    """Imported lazily: `refer` imports this module's tier vocabulary, so a
    module-level import here would be circular."""
    from evals.harness import refer
    return refer


def served_model_ids(endpoint: str = OMLX_V1, settings_path=None,
                     timeout: float = 10.0) -> list[str]:
    """Model ids the local oMLX server is serving RIGHT NOW.

    Raises on any failure -- a connection error, a 401, malformed JSON. It must
    never return an empty list for an unreachable server: `[]` is a measured
    "serving nothing", and a caller that cannot tell that from "I could not ask"
    will treat a dead server as an empty fleet. Callers that want the soft form use
    `local_candidates`, which turns the exception into an explicit
    `served_known: False`.
    """
    import urllib.request

    from evals.harness.client import DEFAULT_SETTINGS_PATH, _load_settings

    settings = _load_settings(settings_path or DEFAULT_SETTINGS_PATH)
    auth = settings.get("auth")
    key = (auth or {}).get("api_key") if isinstance(auth, dict) else None
    headers = {"Authorization": f"Bearer {key}"} if isinstance(key, str) and key else {}
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/models", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return sorted(m["id"] for m in (data.get("data") or []) if m.get("id"))


def local_candidates(served: list[str] | None = None, *, endpoint: str = OMLX_V1,
                     settings_path=None, timeout: float = 10.0) -> dict:
    """The models a local job may be routed to, and whether we really know.

    Returns {models, served_known, discovery_error}. `served_known` is True only
    when the served fleet was actually observed -- either because the caller passed
    it (tests, and any caller that already asked) or because discovery succeeded.
    When it is False the model list is a FALLBACK: every local alias, which is a
    superset of what is loaded. `show` may print from that; `run` refuses on it.

    Passing `served=[]` is not the same as passing `served=None`: the first says the
    server answered and is serving nothing, the second says nobody asked.
    """
    aliases = set(_refer().ALIASES)
    error = None
    if served is None:
        try:
            served = served_model_ids(endpoint=endpoint, settings_path=settings_path,
                                      timeout=timeout)
        except Exception as e:                      # noqa: BLE001 - any failure is
            error = f"{type(e).__name__}: {e}"      # "we could not ask"
            served = None
    if served is None:
        return {"models": sorted(aliases - REMOTE_ALIASES),
                "served_known": False, "discovery_error": error}
    return {"models": sorted((set(served) & aliases) - REMOTE_ALIASES),
            "served_known": True, "discovery_error": None}


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _published_reason(r: dict) -> str:
    """One honest sentence about PUBLISHED evidence. Never a trial count.

    There are no runs behind this number, so there is nothing here that could
    legitimately say "of 20 test runs" -- that sentence belongs to `_reason` and the
    retired sweeps, and emitting it from this path would be a fabricated measurement.
    """
    skills = r.get("skills") or []
    missing = [s["skill"].replace("_", " ") for s in skills if s.get("pctile") is None]
    if missing or r.get("score") is None:
        gap = ", ".join(missing) or "a required skill"
        return (f"no published figure covers {gap} for this model, so there is no "
                f"verdict to give -- a refusal to guess, not a low score")
    weakest = min(skills, key=lambda s: s["pctile"])
    cut = (" after a literature-assumed quantisation haircut"
           if any(s.get("haircut") for s in skills) else "")
    return (f"published benchmarks put this at {_ordinal(round(weakest['pctile'] * 100))} "
            f"percentile on {weakest['skill'].replace('_', ' ')}{cut}; "
            f"correspondence is {r.get('alias_basis')}")


def _published_sort_key(r: dict):
    """Ascending, so the best candidate is first.

    🔴 PRIMARY KEY IS THE TRUST TIER, NOT THE SCORE. Project ruling, 2026-10-01:
    **cleared-for-hand-off beats highest score.** A hand-off that needs reviewing
    costs the caller a read of the whole output; a marginally weaker answer that
    needs no review costs nothing. So a DELEGATE outranks a higher-scoring VERIFY,
    and the worked case is B4/B5, where this flips the recommendation from
    `K2-Horizon-MoVA-36B-A4B-8bit` at 0.93/VERIFY to `Qwen3.8-27B-8bit` at
    0.91/DELEGATE -- two points of published score traded for not having to check
    the result.

    This reverses the ordering as first shipped, which ranked score-first on the
    argument that `refer`'s tier mixes ability with EVIDENCE QUALITY (K2 is capped
    at VERIFY only because AA publishes one mode-less row for it, not because it is
    weaker). That argument is still true and is still the reason the score is the
    SECOND key and is printed beside the tier -- but it is an argument about what
    the numbers mean, and the ruling is about what the caller pays. The runner-up
    is always in `alternatives`, so a caller who would rather have the higher score
    and do the review can see it and say so.
    """
    return (-_TIER_RANK.get(r["tier"], 0),
            -(r["score"] if r.get("score") is not None else -1.0),
            -_BASIS_RANK.get(r.get("alias_basis"), 0),
            r["model"])


def _published_shell(activity: str, mode: str, reason: str, cand: dict) -> dict:
    """The no-candidate answer, carrying every sweep-only field as None."""
    return {"activity": activity, "mode": mode, "kind": None, "egress": "local",
            "source": "published", "model_ref": None, "best_available": None,
            "tier": UNKNOWN, "job_label": None, "score": None,
            "weakest_skill": None, "published_as": None, "precision": None,
            "alias_basis": None, "candidates": cand["models"],
            "served_known": cand["served_known"],
            "discovery_error": cand["discovery_error"],
            "eff_success": None, "n_trials": None, "pass_rate": None,
            "pass_rate_atoms": None, "headline_basis": None, "void_rate": None,
            "delegable_econ": None, "alternatives": [], "reason": reason}


def recommend_published(activity: str, mode: str = "nothink", *,
                        served: list[str] | None = None, corpus=None,
                        candidates: dict | None = None, endpoint: str = OMLX_V1,
                        settings_path=None) -> dict:
    """Pick the model a job should go to, from PUBLISHED benchmarks only.

    Same dict shape `recommend()` returns, so `bin/route` and any other caller keep
    working -- with the sweep-only fields set to None rather than invented, and the
    published provenance (score, weakest skill, correspondence basis, candidate set)
    added alongside.

    `mode` is accepted and reported for shape compatibility, but note that `refer`
    is mode-BLIND: its aliases name AA's `(Non-reasoning)` rows, which is the mode we
    serve by default, and nothing re-reads them for `--mode think`. That limitation
    is `refer`'s and is documented there; this function does not paper over it.
    """
    refer = _refer()
    cand = candidates if candidates is not None else local_candidates(
        served=served, endpoint=endpoint, settings_path=settings_path)

    if activity not in refer.JOBS:
        return _published_shell(
            activity, mode,
            f"no published-benchmark job kind named {activity!r}; known: "
            f"{', '.join(refer.JOBS)}", cand)
    if not cand["models"]:
        return _published_shell(
            activity, mode,
            "no served model has a published alias, so there is nothing to rank"
            if cand["served_known"] else
            "the local server could not be reached and no alias is available either",
            cand)

    corpus = corpus if corpus is not None else refer.Corpus()
    rows = sorted((refer.assess(m, activity, corpus) for m in cand["models"]),
                  key=_published_sort_key)
    best = rows[0]
    best_tier = best["tier"]
    chosen = best_tier in (DELEGATE, VERIFY)
    best_ref = "omlx/" + best["model"]

    def _brief(r):
        # Same keys `recommend`'s `_brief` emits, so a caller iterating
        # `alternatives` does not KeyError; the sweep-only ones are None.
        return {"model_ref": "omlx/" + r["model"], "tier": r["tier"],
                "score": r["score"], "alias_basis": r["alias_basis"],
                "eff_success": None, "pass_rate": None, "headline_basis": None,
                "void_rate": None, "n_trials": None}

    weakest = min((s for s in best["skills"] if s.get("pctile") is not None),
                  key=lambda s: s["pctile"], default=None)
    out = _published_shell(activity, mode, _published_reason(best), cand)
    out.update({
        "kind": None,
        "job_label": best["job_label"],
        "model_ref": best_ref if chosen else None,
        "best_available": best_ref,
        # Carried through from `refer` UNCHANGED. This path does not re-tier: a
        # second opinion computed here would be a different instrument wearing the
        # same words.
        "tier": best_tier,
        "score": best["score"],
        "weakest_skill": weakest["skill"] if weakest else None,
        "published_as": best["published_as"],
        "precision": best["precision"],
        "alias_basis": best["alias_basis"],
        "alternatives": [_brief(r) for r in rows[1:4]],
    })
    return out


# --------------------------------------------------------------------------------
# Dispatch: actually hand a job to the recommended local model. Needs a live server;
# guarded behind the egress gate; returns the model's text and never stores it.
# --------------------------------------------------------------------------------

class RouteRefused(Exception):
    """Raised when a job is not safe to dispatch locally and --force was not given."""


def run_job(activity: str, prompt: str, *, table: dict | None = None,
            mode: str = "nothink", force: bool = False, client=None,
            settings_path=None, source: str = "published",
            served: list[str] | None = None, corpus=None) -> dict:
    """Dispatch `prompt` to the model recommended for `activity`.

    `source` selects where the recommendation comes from: `published` (the default,
    `refer` over the reference corpus) or `table` (our RETIRED sweep evidence, kept
    reachable for the archived corpus and never the default).

    Refuses (RouteRefused) when: the best local option is DO NOT / UNKNOWN and
    force=True was not given; the chosen model is not in the served fleet; the served
    fleet could not be established at all; or the client's endpoint does not classify
    as local egress.

    🔴 THE SERVED-FLEET GUARD IS NOT LIFTED BY `force`. Forcing a DO-NOT tier is a
    judgement a caller may make with their eyes open. Dispatching to a model that is
    not loaded is not a judgement -- it is the A3/E4/F1 defect, where the retired
    table went on naming `Qwen3-30B-A3B-Instruct-2507-4bit` for three jobs after it
    was deleted from this disk.

    Returns {model_ref, tier, output, finish_reason, verify, truncated, retried,
    reason}. `verify` is True when the tier is VERIFY -- check the output.
    """
    from evals.harness.client import OmlxClient
    from evals.harness.egress import classify, load_sanctioned

    if source not in ("published", "table"):
        raise ValueError(f"unknown recommendation source {source!r}")

    if source == "published":
        cand = local_candidates(served=served, settings_path=settings_path)
        rec = recommend_published(activity, mode=mode, candidates=cand, corpus=corpus)
    else:
        table = table if table is not None else load_table()
        rec = recommend(table, activity, mode=mode)
        cand = local_candidates(served=served, settings_path=settings_path)

    if not cand["served_known"]:
        raise RouteRefused(
            f"cannot establish what oMLX is serving ({cand['discovery_error']}), so "
            f"there is no way to tell a loaded model from a deleted one; refusing to "
            f"dispatch rather than guess")

    if rec["tier"] in (DO_NOT, UNKNOWN) and not force:
        raise RouteRefused(explain(rec))

    model_ref = rec["model_ref"] or rec["best_available"]
    if not model_ref:
        raise RouteRefused(explain(rec))
    # model_ref carries the egress prefix ("omlx/..."); the wire id is the tail.
    target, _, wire_model = model_ref.partition("/")

    if wire_model not in cand["models"]:
        raise RouteRefused(
            f"oMLX does not serve {wire_model!r}, so there is nothing to dispatch to. "
            f"Served and aliased right now: {', '.join(cand['models']) or 'none'}. "
            f"(--force does not lift this: a missing model is not a risk to accept, "
            f"it is an absent endpoint.)")

    client = client or OmlxClient(settings_path=settings_path) if settings_path else (client or OmlxClient())
    endpoint = client.endpoint()
    if classify(target, endpoint, load_sanctioned()) != "local":
        raise RouteRefused(
            f"refusing to dispatch: {model_ref} at {endpoint} does not classify as local egress")

    budgets = (table.get("defaults", {}).get("max_tokens", DEFAULT_MAX_TOKENS)
               if table is not None else DEFAULT_MAX_TOKENS)
    budget = budgets.get(mode, 6000)
    messages = [{"role": "user", "content": prompt}]

    def _attempt(cap):
        resp = client.complete(wire_model, messages, cap, mode == "think")
        choice = (resp.get("choices") or [{}])[0]
        return ((choice.get("message") or {}).get("content", ""),
                choice.get("finish_reason"))

    output, finish = _attempt(budget)
    retried = False
    if finish == "length":
        # Retry once at double the budget, then stop. A second ceiling hit means the
        # budget is not the problem.
        retried = True
        output, finish = _attempt(budget * 2)

    truncated = finish == "length"
    reason = ""
    if truncated:
        # Withhold the fragment rather than hand it back. A response cut off at the
        # token ceiling is as likely to be the model thinking out loud as an answer,
        # and a caller that receives text treats it as the result -- which is how
        # reasoning reaches a document. The measurement side has always refused to
        # score such a run (finish_reason == "length" is VOID, not failed); dispatch
        # now refuses to report one.
        output = ""
        reason = (f"truncated at the token ceiling twice ({budget} then "
                  f"{budget * 2}); no content returned, because a cut-off response "
                  f"may be reasoning rather than an answer")

    return {"model_ref": model_ref, "tier": rec["tier"], "output": output,
            "finish_reason": finish, "verify": rec["tier"] == VERIFY,
            "truncated": truncated, "retried": retried, "reason": reason}
