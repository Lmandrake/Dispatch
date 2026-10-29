"""`delegate coverage`: is the guard running, and what the numbers do NOT mean.

🔴 This implements the third of the cold design review's three acceptance tests for
v1 — "a spawn that bypasses routing is visible as unrouted" (finding H4). A bypassing
spawn leaves no trace in the ledger by construction, so the only way to notice is to
compare the guard's own per-spawn record against the ledger's decisions.

The hard part is not the counting. It is refusing to over-read the result: a spawn and
a decision are different units, so their difference is not a bypass count, and several
tests below exist specifically to pin that the code does not claim otherwise.
"""
import json

from dispatchlib import delegate as D
from dispatchlib import ledger as L


def _health(tmp_path, states):
    p = tmp_path / "health.jsonl"
    p.write_text("".join(json.dumps({"ts": 1, "state": s}) + "\n" for s in states))
    return p


def test_a_missing_health_record_means_the_guard_has_never_run(tmp_path):
    """🔴 The H4 signal. A healthy script with a wrong matcher passes every unit test,
    runs no handler, and raises nothing — an empty record is the ONLY symptom, and it
    is only visible from outside the guard."""
    c = D.coverage(health_path=tmp_path / "absent.jsonl",
                   ledger_path=tmp_path / "l.jsonl")
    assert c["health_present"] is False
    assert c["guard_has_ever_run"] is False
    assert c["spawns_evaluated"] == 0


def test_an_empty_health_record_is_also_never_run(tmp_path):
    p = tmp_path / "health.jsonl"
    p.write_text("")
    c = D.coverage(health_path=p, ledger_path=tmp_path / "l.jsonl")
    assert c["health_present"] is True
    assert c["guard_has_ever_run"] is False


def test_evaluated_rows_count_as_spawns_and_blocks_are_a_subset(tmp_path):
    p = _health(tmp_path, ["evaluated_allow"] * 5 + ["evaluated_block"] * 2)
    c = D.coverage(health_path=p, ledger_path=tmp_path / "l.jsonl")
    assert c["spawns_evaluated"] == 7
    assert c["blocked"] == 2
    assert c["guard_has_ever_run"] is True


def test_not_evaluated_is_degraded_enforcement_and_is_not_a_spawn_count(tmp_path):
    """`not_evaluated` is the one number with an unambiguous meaning: the guard could
    not run and allowed the spawn. It is reported separately from `spawns_evaluated`
    precisely because folding them together would hide it."""
    p = _health(tmp_path, ["evaluated_allow", "not_evaluated", "not_evaluated"])
    c = D.coverage(health_path=p, ledger_path=tmp_path / "l.jsonl")
    assert c["spawns_evaluated"] == 1
    assert c["not_evaluated"] == 2
    assert c["guard_has_ever_run"] is True, (
        "a guard that ran and failed has still run; reporting otherwise would "
        "diagnose a wrong matcher")


def test_a_malformed_health_line_is_counted_not_raised(tmp_path):
    """🔴 The OPPOSITE policy from the ledger, deliberately. The ledger RAISES on a
    bad line because a missing row changes a rate. The health record is diagnostic:
    refusing to read it because one line is broken would withhold the diagnosis at
    exactly the moment something is already wrong."""
    p = tmp_path / "health.jsonl"
    p.write_text(json.dumps({"state": "evaluated_allow"}) + "\n{broken\n")
    c = D.coverage(health_path=p, ledger_path=tmp_path / "l.jsonl")
    assert c["spawns_evaluated"] == 1
    assert c["malformed_health_rows"] == 1


def test_decisions_are_counted_from_the_ledger(tmp_path):
    lp = tmp_path / "l.jsonl"
    for i in range(3):
        L.record_decision(task_kind="E3", destination=f"omlx/m{i}", machine="m",
                           reason="prior-ranked", path=lp)
    c = D.coverage(health_path=_health(tmp_path, ["evaluated_allow"] * 5),
                   ledger_path=lp)
    assert c["decisions_recorded"] == 3
    assert c["count_difference"] == 2


def test_attempt_and_disposition_rows_are_not_counted_as_decisions(tmp_path):
    """Three row types share the file; only DECISION answers "was this routed"."""
    lp = tmp_path / "l.jsonl"
    did = L.record_decision(task_kind="E3", destination="omlx/m", machine="m",
                            reason="prior-ranked", path=lp)
    L.record_attempt(did, "completed", latency_secs=1.0, path=lp)
    L.record_disposition(did, "used-as-is", source="observed_operation", path=lp)
    c = D.coverage(health_path=_health(tmp_path, []), ledger_path=lp)
    assert c["decisions_recorded"] == 1


def test_the_difference_can_be_negative_and_that_is_not_an_error(tmp_path):
    """More decisions than spawns is the ordinary case when work is routed to local
    models, which spawn nothing. A negative difference must not read as a fault."""
    lp = tmp_path / "l.jsonl"
    for i in range(4):
        L.record_decision(task_kind="E3", destination=f"omlx/m{i}", machine="m",
                           reason="prior-ranked", path=lp)
    c = D.coverage(health_path=_health(tmp_path, ["evaluated_allow"]), ledger_path=lp)
    assert c["count_difference"] == -3


def test_coverage_does_not_name_the_difference_a_bypass_count():
    """🔴 A naming test, because the over-reading is the risk, not the arithmetic. The
    key must not be called `bypassed` or `unrouted`: a spawn and a decision are
    different units, and a field name is a claim a reader will believe."""
    keys = set(D.coverage(health_path="/nonexistent", ledger_path="/nonexistent"))
    for forbidden in ("bypassed", "unrouted", "unrouted_spawns", "bypass_count",
                      "ignored"):
        assert forbidden not in keys, (
            f"{forbidden!r} would claim the difference between two unlike counts is a "
            f"count of bypasses")
    assert "count_difference" in keys


def test_the_guard_path_and_health_path_are_outside_this_repo():
    """The guard reports ON the router, so its evidence must survive the router being
    missing. The first version wrote the health record under the router repo, which
    lost the `not_evaluated` row in exactly the case it exists for."""
    repo = str(D.P.REPO)
    assert not str(D.GUARD_HEALTH).startswith(repo)
    assert not str(D.GUARD_HOOK).startswith(repo)
