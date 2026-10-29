"""The routing decision: the ruling it implements, and the five ways it says "no".

Every test passes a capability snapshot in, so none of them touches the network or the
local server -- which is the reason `route` takes a snapshot rather than fetching one.

The decision uses the REAL published corpus and the REAL throughput file, deliberately:
a synthetic prior would let the ranking pass while the thing a caller actually gets is
wrong. So these tests pin ORDERING and REFUSAL properties, never a specific score or
duration, both of which are allowed to move. (CLAUDE.md: pin properties, not data that
is supposed to move.)
"""
import time

import pytest

from dispatchlib import capability as cap
from dispatchlib import delegate as D
from dispatchlib import ledger as L
from dispatchlib import prior as P

FLEET = ["GLM-4.7-Flash-8bit", "K2-Horizon-MoVA-36B-A4B-8bit",
         "Qwen3.5-9B-MLX-4bit", "Qwen3.8-27B-8bit",
         "Qwen3.8-27B-OBLITERATED-OptiQ-4bit"]
GATEWAY = ["region.anthropic.claude-opus-5", "region.anthropic.claude-sonnet-5",
           "nova-pro"]


def _snap(*, local=None, gateway=None, machine="desktop-a"):
    now = time.time()
    loc = ({"possible": True, "listening": True, "models": FLEET, "known": True,
            "error": None} if local is None else local)
    return {"ts": now, "machine": machine, "subscription": "acct-a", "probed": True,
            "can_have_local_models": True,
            "local": {"value": loc, "ts": now, "failed": None},
            "gateway": {"value": {"models": GATEWAY if gateway is None else gateway,
                                  "known": True, "source": "gateway", "error": None},
                        "ts": now, "failed": None}}


@pytest.fixture(scope="module")
def corpus():
    from dispatchlib.omlx import harness
    refer = harness("refer")
    return refer.Corpus()


# --- the ruling ---------------------------------------------------------------

def test_the_chosen_route_is_cleared_for_handoff_not_the_top_score(corpus):
    """🔴 The owner's ruling: among feasible routes, cleared-for-hand-off beats
    highest score. Stated as a property so it survives a corpus refresh."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    assert dec["chosen"] is not None
    assert dec["chosen"].tier == D.DELEGATE
    better = [c for c in dec["ranked"]
              if c.score is not None and dec["chosen"].score is not None
              and c.score > dec["chosen"].score]
    assert all(c.tier != D.DELEGATE for c in better)


def test_the_ranking_is_tier_first_then_score():
    lo = P.DestinationPrior("a", P.LOCAL, tier=D.DELEGATE, score=0.10)
    hi = P.DestinationPrior("b", P.LOCAL, tier=D.VERIFY, score=0.99)
    mid = P.DestinationPrior("c", P.LOCAL, tier=D.DELEGATE, score=0.50)
    order = [p.destination for p in sorted([hi, lo, mid], key=D._sort_key)]
    assert order == ["c", "a", "b"]


def test_want_handoff_refuses_a_verify_and_want_best_accepts_one(corpus):
    """A VERIFY means "check the result". A caller who said they will not read the
    output must not be handed one, and a caller who said they will must not be
    refused."""
    only_verify = ["Qwen3.5-9B-MLX-4bit"]
    snap = _snap(local={"possible": True, "listening": True, "models": only_verify,
                        "known": True, "error": None})
    handoff = D.route("E3", snap=snap, want=D.WANT_HANDOFF, corpus=corpus)
    best = D.route("E3", snap=snap, want=D.WANT_BEST, corpus=corpus)
    assert handoff["chosen"] is None
    assert best["chosen"] is not None and best["chosen"].tier == D.VERIFY
    assert "CHECK THE RESULT" in best["reason"]


def test_a_do_not_tier_is_never_chosen_even_as_the_only_candidate(corpus):
    snap = _snap(local={"possible": True, "listening": True,
                        "models": ["Qwen3.8-27B-OBLITERATED-OptiQ-4bit"],
                        "known": True, "error": None})
    for want in (D.WANT_HANDOFF, D.WANT_BEST):
        assert D.route("E3", snap=snap, want=want, corpus=corpus)["chosen"] is None


# --- S1: the budget filters FIRST, so the fast tier can win -------------------

_OUT = 150


def _squeeze_budget(corpus, want=D.WANT_BEST):
    """A budget that admits the fastest usable candidate but not the cleared one.

    DERIVED from the measured throughput rather than hardcoded, so a re-measurement
    moves the test's input instead of breaking it. The first version hardcoded 6s,
    which was wrong by 4s because the cold model-load dominates at this output
    length -- and a hardcoded constant would have had to be re-guessed after every
    `tools/measure_throughput.py` run.
    """
    cands = D.route("E3", snap=_snap(), want=want, corpus=corpus)["ranked"]
    usable = [c for c in cands if c.tier in (D.DELEGATE, D.VERIFY) and c.tok_per_s]
    cleared = [c for c in usable if c.tier == D.DELEGATE]
    if not cleared or len(usable) < 2:
        pytest.skip("the current fleet has no cleared/fast split to squeeze")
    fastest = max(usable, key=lambda c: c.tok_per_s)
    lo = fastest.secs_for(_OUT)["cold_secs"]
    hi = min(c.secs_for(_OUT)["cold_secs"] for c in cleared)
    if not lo < hi:
        pytest.skip("the cleared model is no longer the slower one")
    return (lo + hi) / 2, fastest, cleared


def test_a_tight_budget_lets_a_faster_weaker_model_win(corpus):
    """🔴 Review finding S1. Quality and speed are anti-correlated across this fleet
    by about 5x, so the cleared model is the slowest. A budget the cleared model
    cannot meet must not leave the caller with nothing when a usable faster one fits
    -- but only if they said they would check it (`--want best`)."""
    budget, fastest, _ = _squeeze_budget(corpus)
    unconstrained = D.route("E3", snap=_snap(), want=D.WANT_BEST, corpus=corpus)
    tight = D.route("E3", snap=_snap(), want=D.WANT_BEST, time_budget_secs=budget,
                    expect_output_tokens=_OUT, corpus=corpus)
    assert unconstrained["chosen"].tier == D.DELEGATE
    assert tight["chosen"] is not None
    assert tight["chosen"].destination != unconstrained["chosen"].destination
    assert tight["chosen"].tok_per_s > unconstrained["chosen"].tok_per_s, (
        "the budget should have selected a faster model, not a better one")


def test_the_fast_tier_is_not_globally_dominated(corpus):
    """The drop-list defect, as a test: a model that never wins unconstrained can
    still be the only feasible route, so a ranking built on score alone would have
    deleted it."""
    budget, fastest, cleared = _squeeze_budget(corpus)
    tight = D.route("E3", snap=_snap(), want=D.WANT_BEST, time_budget_secs=budget,
                    expect_output_tokens=_OUT, corpus=corpus)
    assert tight["chosen"] is not None
    assert tight["chosen"].score < min(c.score for c in cleared if c.score), (
        "the feasible pick scores BELOW the cleared one -- which is the whole point: "
        "a score-only ranking would have dropped it from the fleet")


# --- S2: no route meets both requirements ------------------------------------

def test_when_nothing_satisfies_both_requirements_both_relaxations_are_named(corpus):
    """🔴 Review finding S2. Never a silently relaxed review requirement, never a
    pretended deadline -- which requirement to drop is the caller's call."""
    dec = D.route("E3", snap=_snap(), want=D.WANT_HANDOFF, time_budget_secs=8,
                  expect_output_tokens=150, corpus=corpus)
    assert dec["chosen"] is None
    drops = [r["drop"] for r in dec["relaxations"]]
    assert any("hand-off" in d for d in drops)
    assert any("budget" in d for d in drops)
    assert any("local" in d for d in drops)
    for r in dec["relaxations"]:
        assert r["gives"] and r["cost"], "a relaxation must name what it costs"


def test_a_budget_with_no_output_assumption_cannot_filter_and_says_so(corpus):
    """🔴 Review finding S4. The only speed evidence is a generation rate, so a
    duration needs an assumed output length. Filtering on a guessed one would make
    the budget a fabricated promise."""
    dec = D.route("E3", snap=_snap(), time_budget_secs=1, corpus=corpus)
    assert dec["budget_unusable"]
    assert "--expect-output" in dec["budget_unusable"]
    assert dec["chosen"] is not None, "an unusable budget must not refuse the route"
    assert not any(r["why"] == "over-time-budget" for r in dec["rejected"])


def test_warm_would_fit_is_reported_separately_from_too_slow(corpus):
    """The filter uses the COLD estimate, because a snapshot cannot tell whether oMLX
    still has the weights resident. "Would have fitted if loaded" is a different
    answer from "too slow", and collapsing them hides the fast tier behind a one-off
    load cost."""
    dec = D.route("E3", snap=_snap(), want=D.WANT_HANDOFF, time_budget_secs=8,
                  expect_output_tokens=150, corpus=corpus)
    marginal = {m["destination"] for m in dec["budget_marginal"]}
    assert marginal, "expected at least one model whose warm time fits but cold does not"
    for m in dec["budget_marginal"]:
        assert m["warm_secs"] <= 8 < m["cold_secs"]


def test_a_model_with_no_measured_speed_is_kept_not_dropped(corpus, monkeypatch):
    """Unknown is not "too slow". A model we have never timed must not be filtered
    out by a budget -- that would be the collapse this module forbids everywhere
    else, applied to duration."""
    monkeypatch.setattr(P, "_throughput", lambda: {})
    dec = D.route("E3", snap=_snap(), want=D.WANT_HANDOFF, time_budget_secs=1,
                  expect_output_tokens=150, corpus=corpus)
    assert dec["chosen"] is not None
    assert not any(r["why"] == "over-time-budget" for r in dec["rejected"])


# --- the five ways the local fleet can be absent ------------------------------

def test_no_observation_is_unknown_not_empty(corpus):
    snap = _snap()
    snap["local"]["ts"] = time.time() - 10_000          # stale observation
    dec = D.route("E3", snap=snap, corpus=corpus)
    assert dec["chosen"] is None
    assert {"destination": "omlx/*", "why": "unknown"} in dec["rejected"]
    assert "not empty" in dec["reason"]


def test_the_wrong_machine_is_declared_not_probed(corpus):
    dec = D.route("E3", snap=_snap(
        local={"possible": False, "listening": False, "models": [], "known": True,
               "error": None}, machine="laptop-a"), corpus=corpus)
    assert {"destination": "omlx/*", "why": "wrong-machine"} in dec["rejected"]
    assert "declared, not" in dec["reason"]


def test_a_server_that_is_down_is_unreachable(corpus):
    dec = D.route("E3", snap=_snap(
        local={"possible": True, "listening": False, "models": [], "known": True,
               "error": "nothing listening"}), corpus=corpus)
    assert {"destination": "omlx/*", "why": "unreachable"} in dec["rejected"]


def test_a_server_that_will_not_list_is_unknown_not_an_empty_fleet(corpus):
    """🔴 The masked-401 state, carried all the way to the routing answer. The
    roster-loss defect in this repo was exactly an unreachable endpoint reading as an
    empty one."""
    dec = D.route("E3", snap=_snap(
        local={"possible": True, "listening": True, "models": [], "known": False,
               "error": "HTTPError: 401"}), corpus=corpus)
    assert {"destination": "omlx/*", "why": "unknown"} in dec["rejected"]
    assert "empty fleet" in dec["reason"]
    assert "401" in dec["reason"]


def test_served_but_unaliased_models_give_no_candidates(corpus):
    dec = D.route("E3", snap=_snap(
        local={"possible": True, "listening": True, "models": ["mystery-model"],
               "known": True, "error": None}), corpus=corpus)
    assert {"destination": "omlx/*", "why": "no-published-figure"} in dec["rejected"]


# --- override -----------------------------------------------------------------

def test_an_override_is_honoured_and_labelled_owner_specified(corpus):
    dec = D.route("E3", snap=_snap(), force="Qwen3.5-9B-MLX-4bit", corpus=corpus)
    assert dec["chosen"].destination == "omlx/Qwen3.5-9B-MLX-4bit"
    assert dec["reason_code"] == "owner-specified"
    assert dec["chosen"].tier in (D.VERIFY, D.DELEGATE, D.DO_NOT, D.UNKNOWN)


def test_an_override_can_force_a_tier_the_ranking_would_refuse(corpus):
    """Forcing a DO-NOT is a judgement a caller may make with their eyes open."""
    dec = D.route("E3", snap=_snap(),
                  force="Qwen3.8-27B-OBLITERATED-OptiQ-4bit", corpus=corpus)
    assert dec["chosen"] is not None and dec["chosen"].tier == D.DO_NOT


def test_an_override_cannot_make_an_unserved_destination_reachable(corpus):
    """🔴 Review finding A4/A5: an override chooses a destination; it does not make
    one reachable. A forced absent model is refused EXPLICITLY, never quietly
    replaced with the ranking's pick -- a silent fallback is how an override becomes
    indistinguishable from being ignored."""
    dec = D.route("E3", snap=_snap(), force="some-model-we-deleted", corpus=corpus)
    assert dec["chosen"] is None
    assert dec["reason_code"] == "forced"
    assert "cannot make one reachable" in dec["reason"]
    assert {"destination": "some-model-we-deleted", "why": "not-served"} \
        in dec["rejected"]


# --- the escalation path is reported, never ranked ----------------------------

def test_the_sanctioned_path_is_separate_and_carries_no_tier(corpus):
    """🔴 The T3 error, one level up. A `refer` tier and an intelligence index are
    unlike quantities; pooling them would put a 27B above Opus 5 on "hand-off
    clearance" and read as a measurement."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    assert dec["escalation"], "the gateway families should be reported"
    for e in dec["escalation"]:
        assert e.kind == P.SANCTIONED
        assert e.tier == D.UNKNOWN
        assert e.score is None
        assert e not in dec["ranked"]
        assert e.index_lo is not None and e.usd_lo is not None


def test_the_sanctioned_figures_are_intervals_across_effort(corpus):
    """Our requests set no reasoning effort and AA publishes one row per level, so no
    single row describes what we would get."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    opus = next(e for e in dec["escalation"] if "opus-5" in e.destination)
    assert opus.index_hi > opus.index_lo
    assert opus.usd_hi > opus.usd_lo
    assert "effort_is_unspecified" in opus.unknowns


def test_an_unaliased_gateway_id_is_not_offered_as_an_escalation(corpus):
    dec = D.route("E3", snap=_snap(gateway=["nova-pro"]), corpus=corpus)
    assert dec["escalation"] == []


def test_consults_are_listed_with_no_numbers_at_all(corpus):
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    assert len(dec["consults"]) == len(P.CONSULTS)
    for c in dec["consults"]:
        assert c.tier == D.UNKNOWN and c.score is None and c.index_lo is None
        assert "no_corpus_for_two_consults" in c.unknowns


# --- the unknowns are derived, never retyped ---------------------------------

def test_the_unknowns_are_computed_from_the_gap_table(corpus):
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    assert dec["unknowns"], "a local route always has at least two open gaps"
    for text in dec["unknowns"]:
        assert text in P.GAPS.values(), "prose stating a fact must come from the data"


def test_every_local_route_warns_that_availability_is_not_capacity(corpus):
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    assert dec["capacity_note"] == D.CAPACITY_NOTE
    assert "serially" in dec["capacity_note"]


def test_every_job_kind_routes_without_raising(corpus):
    from dispatchlib.omlx import harness
    refer = harness("refer")
    assert len(refer.JOBS) >= 8
    for job in refer.JOBS:
        dec = D.route(job, snap=_snap(), want=D.WANT_BEST, corpus=corpus)
        assert dec["reason"], f"{job} produced no reason"
        if dec["chosen"] is not None:
            assert dec["chosen"].tier in (D.DELEGATE, D.VERIFY)


# --- recording ---------------------------------------------------------------

def test_a_decision_with_no_output_assumption_predicts_no_duration(tmp_path, corpus):
    """`0` would claim a measured zero and a number would be invented from a
    generation rate. None is the honest value."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    did = D.record(dec, path=tmp_path / "l.jsonl")
    row = next(r for r in L.read(tmp_path / "l.jsonl") if r["decision_id"] == did)
    assert row["predicted_secs"] is None
    assert row["predicted_usd"] is None, (
        "local cost depends on a duty-cycle assumption; attaching one here would "
        "present an assumption as a prediction")
    assert row["predicted_tier"] == D.DELEGATE
    assert row["basis"] == "provisional" and row["n_dispositions"] == 0


def test_a_decision_with_an_output_assumption_predicts_the_cold_duration(tmp_path,
                                                                         corpus):
    dec = D.route("E3", snap=_snap(), expect_output_tokens=200, corpus=corpus)
    did = D.record(dec, path=tmp_path / "l.jsonl")
    row = next(r for r in L.read(tmp_path / "l.jsonl") if r["decision_id"] == did)
    assert row["predicted_secs"] > 0


def test_a_no_route_decision_is_still_recorded(tmp_path, corpus):
    """A refusal is a decision. Not recording it would make the ledger's own
    denominator wrong -- it would only ever contain routes that worked."""
    dec = D.route("E3", snap=_snap(), time_budget_secs=8, expect_output_tokens=150,
                  corpus=corpus)
    assert dec["chosen"] is None
    did = D.record(dec, path=tmp_path / "l.jsonl")
    row = next(r for r in L.read(tmp_path / "l.jsonl") if r["decision_id"] == did)
    assert row["destination"] is None and row["reason"] == "no-candidate"
    assert any(r["why"] == "over-time-budget" for r in row["rejected"])


def test_a_recorded_decision_carries_the_config_fingerprint(tmp_path, corpus):
    """Review finding A2: swap a re-quantised build in under the same served name and
    a favourable cell would keep applying to a different artifact."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    did = D.record(dec, path=tmp_path / "l.jsonl")
    row = next(r for r in L.read(tmp_path / "l.jsonl") if r["decision_id"] == did)
    assert row["config_fingerprint"]
    assert row["config_fingerprint"] == dec["chosen"].config_fingerprint


def test_the_eligible_set_is_recorded_so_exploration_is_auditable_later(tmp_path,
                                                                       corpus):
    """Not used in v1 -- exploration is designed and not built -- but the eligible set
    is what any later challenger assignment has to be judged against, and it is only
    knowable at decision time."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    did = D.record(dec, path=tmp_path / "l.jsonl")
    row = next(r for r in L.read(tmp_path / "l.jsonl") if r["decision_id"] == did)
    assert len(row["eligible"]) == len(dec["ranked"]) >= 2


# --- cost: the only comparison that is like-for-like ---------------------------

def test_local_is_priced_and_is_not_free(corpus):
    """🔴 Local inference is NOT free and electricity is the small half: the machine
    is ~18x the power. Printing nothing beside the gateway's dollar figure reads as
    free, which is the same error with the decimal point moved."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    usd = dec["chosen"].usd_for(400)
    assert usd and usd["lo"] > 0 and usd["hi"] > usd["lo"]
    assert "hardware amortised" in usd["basis"]
    assert "duty cycle" in usd["basis"], (
        "the duty cycle is the load-bearing guess and must be named, not inherited")


def test_the_sanctioned_cost_is_priced_per_token_not_per_index_task(corpus):
    """🔴 `usd_lo/hi` on a sanctioned prior is per AA INDEX TASK -- ~27k output tokens
    for Sonnet 5, so ~68x a 400-token job. Printing it beside a local per-job figure
    reads as "local is 100x cheaper" when the tasks differ by 68x in length. Only the
    blended per-1M price makes the two comparable."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    sanc = next(e for e in dec["escalation"] if "sonnet-5" in e.destination)
    per_task = sanc.usd_lo
    per_job = sanc.usd_for(400)
    assert per_job is not None
    assert per_job["lo"] < per_task / 10, (
        "a 400-token job must cost far less than a 27k-token index task; if these are "
        "close, the per-token path is reading the per-task field")
    assert "per 1M" in per_job["basis"] or "/1M" in per_job["basis"]
    assert "blended" in per_job["basis"]


def test_the_two_cost_figures_scale_with_the_token_count(corpus):
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    sanc = next(e for e in dec["escalation"] if "sonnet-5" in e.destination)
    for p in (dec["chosen"], sanc):
        a, b = p.usd_for(100), p.usd_for(1000)
        assert b["lo"] > a["lo"]
        assert abs(b["lo"] / a["lo"] - 10) < 0.01, "cost must be linear in tokens"


def test_a_destination_with_no_price_returns_none_not_zero(corpus):
    """`0` would claim a measured zero -- i.e. free."""
    nothing = P.DestinationPrior("consult/x", P.CONSULT)
    assert nothing.usd_for(400) is None
    no_rate = P.DestinationPrior("omlx/x", P.LOCAL, tok_per_s=None)
    assert no_rate.usd_for(400) is None
    no_price = P.DestinationPrior("sanctioned/x", P.SANCTIONED, price_1m_lo=None)
    assert no_price.usd_for(400) is None


def test_a_short_job_can_cost_more_locally_than_on_the_gateway(corpus):
    """Not an assertion about the current prices -- a check that the comparison is
    CAPABLE of inverting, which is the finding the per-task figures hid. If the
    numbers move so that local is cheaper at every size, this skips rather than
    silently becoming vacuous."""
    dec = D.route("E3", snap=_snap(), corpus=corpus)
    local = dec["chosen"].usd_for(400)
    cheaper = [e for e in dec["escalation"]
               if e.usd_for(400) and e.usd_for(400)["lo"] < local["lo"]]
    if not cheaper:
        pytest.skip("no sanctioned model is currently cheaper at this size")
    assert all(e.kind == P.SANCTIONED for e in cheaper)
