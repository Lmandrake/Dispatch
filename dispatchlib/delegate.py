"""The routing decision: where this work should go, on this machine, right now.

One function does the deciding (`route`) and `bin/delegate` prints it. Nothing is
restated in prose anywhere else -- that is the whole point of the component. Delegation
ladders restated in several files drift apart. Prose restated in N places becomes N ladders.

🔴 THE RANKING, AND THE ONE RULE THAT OUTRANKS THE SCORE.

Project ruling: **among feasible routes, cleared-for-hand-off beats
highest score.** A hand-off that needs reviewing costs the caller a read of the whole
output; a marginally weaker answer that needs no review costs nothing.

"Among feasible" is load-bearing and came out of the cold design review (finding S1).
Quality and speed are anti-correlated across this fleet by about 5x: the cleared model
is `Qwen3.8-27B-8bit` at 15.3 tok/s, and `Qwen3.5-9B-MLX-4bit` runs 78.8 tok/s at
VERIFY. With a six-second budget the fast one is the only candidate; with no budget the
cleared one wins. So a time budget filters FIRST and the ruling orders what survives --
the fast tier is not globally dominated just because something scores higher.

🔴 WHEN NOTHING SATISFIES BOTH REQUIREMENTS, SAY SO (finding S2). If the only cleared
route takes 28 s and the caller wants an unattended hand-off inside 6 s, the answer is
"no route meets both requirements", with the two relaxations named. It is never a
silently relaxed review requirement and never a pretended deadline.

🔴 A TIME BUDGET IS NOT A COMPLETION FORECAST (finding S4). Our only speed measurement
is one short warm prompt. So a budget filters on an ESTIMATE whose assumptions are
printed, and `route` says plainly that it cannot promise completion. A budget given
without an output-token assumption cannot filter at all, and that is reported rather
than guessed around.

🔴 AVAILABILITY IS NOT CAPACITY (finding S3, unsolved and stated). Five routes each
reading "local is idle" from one cached snapshot each predict four seconds; oMLX
executes serially and the last finishes around twenty. A snapshot cannot reserve
capacity. The fix belongs in an execution adapter with an atomic reservation and is
not built, so `route` carries `capacity_note` on every local answer.

Pure stdlib. `route` does no I/O at all: the caller passes a capability snapshot in,
which is what makes the whole decision testable without a server.
"""

from __future__ import annotations

import json
import os
import pathlib

from dispatchlib import capability as cap
from dispatchlib import ledger as L
from dispatchlib import prior as P

DELEGATE = "DELEGATE"
VERIFY = "VERIFY"
DO_NOT = "DO NOT"
UNKNOWN = "UNKNOWN"
_TIER_RANK = {DELEGATE: 3, VERIFY: 2, DO_NOT: 1, UNKNOWN: 0}

WANT_HANDOFF = "handoff"
WANT_BEST = "best"

CAPACITY_NOTE = (
    "oMLX executes serially, and a snapshot cannot reserve capacity: N concurrent "
    "routes each reading 'idle' will each predict the single-job time. Treat a "
    "duration estimate as valid for ONE job at a time.")


def _sort_key(p: P.DestinationPrior):
    """Ascending, best first. Tier, then score, then correspondence quality, then
    name for determinism. The owner's ruling is the primary key; see the module
    docstring for why it is not the score."""
    return (-_TIER_RANK.get(p.tier, 0),
            -(p.score if p.score is not None else -1.0),
            -{"measured": 3, "proxy": 2, "estimated": 1, "direct": 0}
            .get(p.alias_basis, 0),
            p.destination)


def route(task_kind: str, *, snap: dict, want: str = WANT_HANDOFF,
          time_budget_secs: float | None = None,
          expect_output_tokens: int | None = None,
          size_input_tokens: int | None = None,
          force: str | None = None, corpus=None) -> dict:
    """Decide where `task_kind` should go. No I/O; `snap` is the ground truth.

    `want=handoff` (the default) requires a DELEGATE tier -- the caller is saying
    they will not read the output. `want=best` accepts VERIFY as well and says so.

    `force` names a destination directly; it is honoured, recorded with reason
    `owner-specified`, and -- per review finding A5/A4 -- **an override chooses a
    destination, it does not make one reachable.** A forced destination that is not
    served is refused explicitly rather than quietly falling back.
    """
    machine = snap.get("machine") if snap else cap.machine_key()
    local_obs = cap.observation(snap, "local") or {}
    gw_obs = cap.observation(snap, "gateway") or {}
    gw_models = gw_obs.get("models") or []

    out = {
        "task_kind": task_kind, "machine": machine, "want": want,
        "time_budget_secs": time_budget_secs,
        "expect_output_tokens": expect_output_tokens,
        "size_input_tokens": size_input_tokens,
        "chosen": None, "reason": None, "reason_code": "no-candidate",
        "ranked": [], "rejected": [], "escalation": P.sanctioned_priors(gw_models),
        "consults": P.consult_priors(), "unknowns": [], "capacity_note": None,
        "budget_unusable": None, "relaxations": [], "budget_marginal": [],
    }

    # --- is there a local fleet at all? Three distinguishable answers. -----------
    if not local_obs:
        out["rejected"].append({"destination": "omlx/*", "why": "unknown"})
        out["reason"] = ("no fresh observation of the local server, so the local "
                         "fleet is unknown -- not empty")
        out["unknowns"] = P.unknowns_text(["no_rate_limits"])
        return out
    if not local_obs.get("possible"):
        out["rejected"].append({"destination": "omlx/*", "why": "wrong-machine"})
        out["reason"] = (f"{machine} does not serve local models (declared, not "
                         f"probed); the sanctioned gateway is the route here")
        return out
    if not local_obs.get("listening"):
        out["rejected"].append({"destination": "omlx/*", "why": "unreachable"})
        out["reason"] = "oMLX is not listening on this machine"
        return out
    if not local_obs.get("known"):
        out["rejected"].append({"destination": "omlx/*", "why": "unknown"})
        out["reason"] = (f"oMLX answered but would not list its models "
                         f"({local_obs.get('error')}); refusing to treat that as an "
                         f"empty fleet")
        return out

    served = local_obs.get("models") or []
    cands = P.local_priors(task_kind, served, corpus)
    if not cands:
        out["rejected"].append({"destination": "omlx/*", "why": "no-published-figure"})
        out["reason"] = ("oMLX is serving models but none has a published alias, so "
                         "there is no figure to rank")
        return out

    out["capacity_note"] = CAPACITY_NOTE
    gaps = sorted({g for c in cands for g in c.unknowns})
    out["unknowns"] = P.unknowns_text(gaps)

    # --- a forced destination short-circuits the ranking, but not reachability ---
    if force:
        hit = next((c for c in cands if c.destination == force
                    or c.destination.endswith("/" + force)), None)
        if hit is None:
            out["reason_code"] = "forced"
            out["reason"] = (
                f"{force!r} is not in the served and aliased local fleet "
                f"({', '.join(sorted(served)) or 'none'}). An override chooses a "
                f"destination; it cannot make one reachable, so this is refused "
                f"rather than quietly replaced.")
            out["rejected"].append({"destination": force, "why": "not-served"})
            return out
        out["chosen"] = hit
        out["reason_code"] = "owner-specified"
        out["reason"] = (f"routed to {hit.destination} because it was named "
                         f"explicitly; published evidence rates it {hit.tier}")
        out["ranked"] = sorted(cands, key=_sort_key)
        return out

    # --- feasibility: the time budget filters BEFORE the ruling orders ----------
    feasible = list(cands)
    if time_budget_secs is not None:
        if expect_output_tokens is None:
            out["budget_unusable"] = (
                f"a {time_budget_secs}s budget was given with no expected output "
                f"length, and the only speed evidence here is a generation rate -- "
                f"so nothing can be filtered. Pass --expect-output N to use the "
                f"budget, and read it as an estimate, never a completion promise.")
        else:
            # 🔴 THE FILTER IS ON THE COLD ESTIMATE, and the marginal cases are
            # reported rather than silently dropped. We cannot tell from a snapshot
            # whether a given model is resident -- oMLX may have unloaded it -- so
            # filtering on the warm figure would promise a duration that depends on
            # a fact nobody observed. Filtering on cold is the conservative
            # direction. But "would have fitted if it were already loaded" is a
            # genuinely different answer from "too slow", and collapsing them hides
            # the whole fast tier behind a one-off load cost.
            keep, marginal = [], []
            for c in cands:
                est = c.secs_for(expect_output_tokens)
                if est is None:
                    keep.append(c)                      # no rate = unknown = keep
                elif est["cold_secs"] <= time_budget_secs:
                    keep.append(c)
                else:
                    out["rejected"].append({"destination": c.destination,
                                            "why": "over-time-budget"})
                    if est["warm_secs"] <= time_budget_secs:
                        marginal.append({"destination": c.destination,
                                         "tier": c.tier,
                                         "warm_secs": est["warm_secs"],
                                         "cold_secs": est["cold_secs"]})
            feasible = keep
            out["budget_marginal"] = marginal

    ranked = sorted(feasible, key=_sort_key)
    out["ranked"] = ranked

    allowed = ({DELEGATE} if want == WANT_HANDOFF else {DELEGATE, VERIFY})
    pick = next((c for c in ranked if c.tier in allowed), None)

    for c in ranked:
        if pick is not None and c.destination == pick.destination:
            continue
        out["rejected"].append({
            "destination": c.destination,
            "why": ("tier-too-low" if c.tier in (DO_NOT,) else
                    "no-published-figure" if c.tier == UNKNOWN else
                    "tier-too-low" if c.tier not in allowed else "lower-ranked")})

    if pick is None:
        out["reason_code"] = "no-candidate"
        out["reason"], out["relaxations"] = _no_route(
            cands, feasible, want, time_budget_secs, expect_output_tokens)
        return out

    out["chosen"] = pick
    out["reason_code"] = ("only-candidate" if len(ranked) == 1 else "prior-ranked")
    est = pick.secs_for(expect_output_tokens) if expect_output_tokens else None
    out["reason"] = _reason(pick, want, est)
    return out


def _no_route(cands, feasible, want, budget, expect) -> tuple[str, list]:
    """🔴 The S2 answer: name BOTH relaxations rather than picking one silently.

    Which requirement to drop is the caller's call, always. Relaxing the review
    requirement on their behalf hands them an unchecked output they said they would
    not read; relaxing the deadline hands them a job that misses it.
    """
    relax = []
    cleared_anywhere = [c for c in cands if c.tier == DELEGATE]
    usable_feasible = [c for c in feasible if c.tier in (DELEGATE, VERIFY)]

    if want == WANT_HANDOFF and usable_feasible:
        relax.append({
            "drop": "the hand-off requirement",
            "gives": usable_feasible[0].destination,
            "cost": "you would have to check the result"})
    if budget is not None and expect is not None and cleared_anywhere:
        best_cleared = min(cleared_anywhere, key=_sort_key)
        est = best_cleared.secs_for(expect)
        relax.append({
            "drop": f"the {budget}s budget",
            "gives": best_cleared.destination,
            "cost": (f"estimated {est['cold_secs']}s cold / {est['warm_secs']}s warm"
                     if est else "duration unknown")})
    relax.append({"drop": "staying local",
                  "gives": "the sanctioned gateway",
                  "cost": "it costs money and leaves this machine"})

    if not cands:
        return "nothing local is a candidate for this job", relax
    if want == WANT_HANDOFF and not cleared_anywhere:
        return ("no local model is cleared for an unattended hand-off on this job; "
                "published evidence rates the best of them "
                f"{min(cands, key=_sort_key).tier}"), relax
    return ("no route meets both requirements -- nothing that is cleared for "
            "hand-off also fits the time budget"), relax


def _reason(p: P.DestinationPrior, want: str, est: dict | None) -> str:
    bits = []
    if p.tier == DELEGATE:
        bits.append("cleared for hand-off: published benchmarks put its weakest "
                    f"required skill ({(p.weakest_skill or 'n/a').replace('_',' ')}) "
                    f"at {round((p.score or 0) * 100)}th percentile and it clears the "
                    f"absolute floor")
    elif p.tier == VERIFY:
        bits.append(f"usable but CHECK THE RESULT: {p.tier} because the evidence is "
                    f"{p.alias_basis} correspondence or a mid-band score "
                    f"({round((p.score or 0) * 100)}th percentile on "
                    f"{(p.weakest_skill or 'n/a').replace('_',' ')})")
    else:
        bits.append(f"tier {p.tier}")
    if est:
        bits.append(f"estimated {est['warm_secs']}s warm / {est['cold_secs']}s cold "
                    f"for {est['assumed_output_tokens']} output tokens")
    if "no_quantisation_figures" in p.unknowns:
        bits.append("the quantisation haircut behind that percentile is "
                    "literature-derived, never measured")
    return "; ".join(bits)


# -------------------------------------------------------- recording the decision --

def record(decision: dict, *, batch_id: str | None = None,
           note: str | None = None, path=L.DEFAULT_LEDGER_PATH) -> str:
    """Write the DECISION row for a `route` result and return its id.

    The prediction stored is whatever `route` could honestly produce: `predicted_secs`
    is None when no output length was assumed, because a duration invented from a
    generation rate is a fabricated measurement, and `0` would claim one.

    `predicted_usd` is None for every local route on purpose. Local inference is not
    free -- `costmap` prices it as electricity plus amortised hardware -- but that
    price depends on a duty-cycle assumption, and attaching a per-task dollar figure
    here would present an assumption as a prediction. The escalation path carries real
    published costs; the local path carries none.
    """
    pick = decision.get("chosen")
    est = (pick.secs_for(decision["expect_output_tokens"])
           if pick and decision.get("expect_output_tokens") else None)
    basis, n = ("provisional", 0)
    if pick:
        basis, n = L.cell_basis(L.read(path), pick.destination,
                                decision["task_kind"])
    return L.record_decision(
        task_kind=decision["task_kind"],
        destination=pick.destination if pick else None,
        machine=decision["machine"],
        reason=decision["reason_code"],
        network={"local": bool((decision.get("ranked") or [])),
                 "enterprise": None},
        size_input_tokens=decision.get("size_input_tokens"),
        want=decision.get("want"),
        time_budget_secs=decision.get("time_budget_secs"),
        rejected=decision.get("rejected") or [],
        predicted_usd=None,
        predicted_secs=est["cold_secs"] if est else None,
        predicted_tier=pick.tier if pick else None,
        basis=basis, n_dispositions=n, batch_id=batch_id,
        config_fingerprint=pick.config_fingerprint if pick else None,
        eligible=[c.destination for c in decision.get("ranked") or []],
        note=note, path=path)


# ------------------------------------------------- is the guard actually running --

#: Where the spawn guard writes its three-state health record. Kept OUTSIDE this repo
#: on purpose: the guard reports on the router, so its evidence must survive the
#: router being missing. See the guard hook's own notes.
GUARD_HEALTH = pathlib.Path(os.environ.get("DISPATCH_GUARD_HEALTH")
                            or pathlib.Path.home() / ".config" / "dispatch" / "route-guard-health.jsonl")

#: The guard itself. Its absence and its silence are different findings.
GUARD_HOOK = pathlib.Path(os.environ.get("DISPATCH_GUARD_HOOK")
                          or pathlib.Path.home() / ".config" / "dispatch" / "route-agent-spawn.py")


def coverage(*, health_path=None, ledger_path=L.DEFAULT_LEDGER_PATH) -> dict:
    """How much delegation the router can actually see — and what that does NOT prove.

    🔴 THIS IS THE THIRD OF THE REVIEW'S THREE ACCEPTANCE TESTS: "a spawn that
    bypasses routing is visible as unrouted" (finding H4). The guard runs on every
    subagent spawn and writes one row per spawn; `route --record` writes one DECISION
    per routing question. Comparing the counts is the only way to notice that the
    router is being ignored, because a bypassing spawn leaves no trace in the ledger
    by construction.

    🔴 AND HERE IS WHAT THE COMPARISON CANNOT SAY. A spawn and a decision are not the
    same unit: a decision may route work to a local model with no spawn at all, and a
    spawn may be one step of a task that was routed once. So `unrouted_spawns` is a
    DIFFERENCE BETWEEN TWO COUNTS, not a count of bypasses, and this function refuses
    to call it one. Two inferences are sound and are the reason it exists:

      * `not_evaluated > 0` means enforcement was DEGRADED for that many spawns — the
        guard could not run and allowed the spawn. That is the one number with an
        unambiguous meaning.
      * `spawns == 0` with a session that has spawned agents means the guard is NOT
        INSTALLED or its matcher is wrong. A healthy script with a wrong matcher
        passes every unit test, runs no handler, and raises nothing; an empty record is
        the only symptom, and it is only visible from outside the guard.
    """
    health_path = pathlib.Path(health_path or GUARD_HEALTH)
    states: dict[str, int] = {}
    malformed = 0
    if health_path.exists():
        for line in health_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                state = json.loads(line).get("state", "?")
            except Exception:                           # noqa: BLE001
                # Counted, not raised. The health record is diagnostic: refusing to
                # read it because one line is broken would withhold the diagnosis.
                # (The LEDGER raises on a bad line, because there a missing row
                # changes a rate.)
                malformed += 1
                continue
            states[state] = states.get(state, 0) + 1

    decisions = [r for r in L.read(ledger_path) if r.get("row") == L.DECISION]
    spawns = states.get("evaluated_allow", 0) + states.get("evaluated_block", 0)
    return {
        "health_path": str(health_path),
        "health_present": health_path.exists(),
        "spawns_evaluated": spawns,
        "blocked": states.get("evaluated_block", 0),
        "not_evaluated": states.get("not_evaluated", 0),
        "malformed_health_rows": malformed,
        "decisions_recorded": len(decisions),
        "count_difference": spawns - len(decisions),
        "guard_installed": GUARD_HOOK.exists(),
        "guard_has_ever_run": spawns + states.get("not_evaluated", 0) > 0,
    }
