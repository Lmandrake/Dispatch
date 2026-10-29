"""The disposition ledger: what it refuses to store, and what it refuses to claim.

Most of these tests exist because of a specific finding in the cold design review
(`docs/ROUTER_CONSULT.md`); each names its finding id, so a later reader can tell a
rule that was argued for from one that was assumed.

The house four-case calibration -- known positive, known negative, EMPTY, TRUNCATED --
is applied to `read`, which is the only function here that parses something it did not
write.
"""
import json

import pytest

from dispatchlib import ledger as L


def _dec(**kw):
    row = {"row": L.DECISION, "decision_id": "d1", "task_kind": "E3",
           "destination": "omlx/Qwen3.8-27B-8bit", "machine": "desktop-a",
           "reason": "prior-ranked", "rule_version": L.ACTUATION["version"]}
    row.update(kw)
    return row


def _disp(**kw):
    row = {"row": L.DISPOSITION, "decision_id": "d1", "disposition": "used-as-is",
           "disposition_source": "observed_operation",
           "rule_version": L.ACTUATION["version"]}
    row.update(kw)
    return row


def _att(**kw):
    row = {"row": L.ATTEMPT, "decision_id": "d1", "status": "completed",
           "rule_version": L.ACTUATION["version"]}
    row.update(kw)
    return row


# --- the allowlist, which is what keeps text out of a committed file ------------

def test_an_unknown_key_is_refused_not_passed_through():
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(output="the model said this"))
    assert "allowlist" in str(e.value) and "output" in str(e.value)


def test_a_long_string_is_refused_even_in_an_allowed_field():
    """The allowlist stops a NEW field carrying text; this stops an existing one.
    Both are needed: `note` is capped separately and everything else is an
    identifier."""
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(task_kind="x" * 200))
    assert "capped" in str(e.value)


def test_a_long_string_nested_in_a_list_is_found_too():
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(rejected=[{"destination": "y" * 300, "why": "unreachable"}]))


def test_the_note_is_capped_and_single_line():
    L.check_row(_dec(note="fine"))
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(note="x" * (L.NOTE_MAX + 1)))
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(note="line one\nline two"))
    assert "single line" in str(e.value)


def test_a_wrong_rule_version_is_refused_rather_than_corrected():
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(rule_version=99))
    assert "never pooled" in str(e.value)


# --- A6: the privacy rule has to hold on the ERROR path too --------------------

def test_a_serialised_hook_payload_cannot_be_stored_anywhere(tmp_path):
    """Review finding A6: every normal row is clean while an exception handler
    serialises the whole tool payload into an error field. Both the unknown-key rule
    and the length cap must fire on that shape."""
    payload = {"tool_name": "Agent", "tool_input": {
        "prompt": "Here is the private transcript: " + "x" * 400}}
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(tool_input=json.dumps(payload)))
    # and it cannot sneak in through the one free-text field either
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(note=json.dumps(payload)))


# --- per-row-type rules --------------------------------------------------------

def test_a_decision_with_no_destination_must_say_so():
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(destination=None))
    assert "no-candidate" in str(e.value)
    L.check_row(_dec(destination=None, reason="no-candidate"))


def test_a_rejection_reason_must_be_from_the_enum():
    L.check_row(_dec(rejected=[{"destination": "x", "why": "unreachable"}]))
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(rejected=[{"destination": "x", "why": "it seemed bad"}]))


def test_size_is_input_tokens_and_must_be_a_count():
    """Review: `--size N` was undefined -- input tokens, expected output tokens,
    document count and total context are not interchangeable. The field name now
    says which, and the type check is what stops a float of seconds landing in it."""
    L.check_row(_dec(size_input_tokens=4000))
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_dec(size_input_tokens=-1))
    assert "INPUT" in str(e.value)


def test_a_prediction_we_do_not_have_is_none_not_zero():
    L.check_row(_dec(predicted_secs=None))
    with pytest.raises(L.LedgerRefused):
        L.check_row(_dec(predicted_secs="fast"))


def test_disposition_source_is_required():
    """Review finding D3. An agent calling `record used-as-is` and then writing
    something different is the grader failure under a new field name; the only
    defence is recording which KIND of claim this is."""
    row = _disp()
    del row["disposition_source"]
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(row)
    assert "REQUIRED" in str(e.value)


def test_an_errored_attempt_must_name_an_error_class():
    L.check_row(_att(status="errored", error_class="invalid-model"))
    with pytest.raises(L.LedgerRefused) as e:
        L.check_row(_att(status="errored"))
    assert "error_class" in str(e.value)


def test_launched_is_a_legal_status_and_is_not_terminal():
    """L3, the measured case: a spawn returns a successful launch and then dies on
    HTTP 400. `launched` must be storable, and `cells` must count it as unfinished."""
    L.check_row(_att(status="launched"))
    assert "launched" in L.ATTEMPT_STATUS


# --- read: the four-case calibration -------------------------------------------

def test_read_a_well_formed_ledger(tmp_path):
    p = tmp_path / "l.jsonl"
    L.append(_dec(), p)
    L.append(_att(), p)
    assert [r["row"] for r in L.read(p)] == [L.DECISION, L.ATTEMPT]


def test_read_a_missing_file_is_an_empty_ledger(tmp_path):
    assert L.read(tmp_path / "nope.jsonl") == []


def test_read_an_empty_file_is_an_empty_ledger(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text("")
    assert L.read(p) == []
    p.write_text("\n\n")
    assert L.read(p) == []


def test_read_raises_on_a_truncated_final_line(tmp_path):
    """A crash mid-write happens during the incidents, so the rows most likely to
    matter are the ones most likely to be truncated. Skipping them silently would
    report FEWER failures than occurred."""
    p = tmp_path / "l.jsonl"
    L.append(_dec(), p)
    with p.open("a") as f:
        f.write('{"row": "ATTEMPT", "decision_id": "d1"')
    with pytest.raises(L.LedgerRefused) as e:
        L.read(p)
    assert "partial ledger" in str(e.value)


# --- append -------------------------------------------------------------------

def test_append_is_idempotent_on_event_id(tmp_path):
    """Duplicate delivery is a real failure of any append-only log, and a duplicated
    disposition would inflate a cell's sample size."""
    p = tmp_path / "l.jsonl"
    row = L.append(_dec(), p)
    L.append(row, p)
    L.append(dict(row), p)
    assert len(L.read(p)) == 1


def test_two_rows_differing_only_in_content_are_both_kept(tmp_path):
    p = tmp_path / "l.jsonl"
    L.append(_dec(), p)
    L.append(_dec(decision_id="d2", destination="omlx/other"), p)
    assert len(L.read(p)) == 2


def test_a_row_naming_no_decision_is_refused(tmp_path):
    p = tmp_path / "l.jsonl"
    L.record_decision(task_kind="E3", destination="omlx/x", machine="m",
                      reason="prior-ranked", path=p)
    with pytest.raises(L.LedgerRefused) as e:
        L.record_disposition("not-a-real-id", "used-as-is", path=p)
    assert "cannot update a cell" in str(e.value)


def test_record_disposition_defaults_to_the_weakest_source(tmp_path):
    """Defaulting the other way would let every self-report count as observed use."""
    p = tmp_path / "l.jsonl"
    did = L.record_decision(task_kind="E3", destination="omlx/x", machine="m",
                            reason="prior-ranked", path=p)
    row = L.record_disposition(did, "used-as-is", path=p)
    assert row["disposition_source"] == "actor_report"


# --- cells: coverage, bounds, and the three rates ------------------------------

def _ledger(n_decisions, dispositions, *, review="none",
            source="observed_operation", batch=None):
    """n decisions against one cell, with `dispositions` (a list, possibly shorter
    than n) recorded against the first ones."""
    rows = []
    for i in range(n_decisions):
        rows.append(_dec(decision_id=f"d{i}", batch_id=batch))
    for i, d in enumerate(dispositions):
        rows.append(_disp(decision_id=f"d{i}", disposition=d,
                          review_status=review, disposition_source=source))
    return rows


def test_an_absent_disposition_stays_unknown_and_bounds_the_rate():
    """🔴 Review finding D6, and one of the three acceptance tests for v1.

    20 recorded of 100 permits a true used-as-is fraction anywhere from 20% to 100%.
    Reporting the recorded 100% alone is the denominator failure this whole repo
    exists to avoid."""
    rows = _ledger(100, ["used-as-is"] * 20)
    c = L.cells(rows)[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_decisions"] == 100
    assert c["n_dispositions"] == 20
    assert c["n_unknown"] == 80
    assert c["clean_rate"] == 1.0            # over what was recorded
    assert c["clean_rate_lo"] == 0.20        # if every unrecorded case were adverse
    assert c["clean_rate_hi"] == 1.0         # if every one were favourable


def test_a_cell_with_no_dispositions_has_no_rate_at_all():
    """`0.0` would claim every hand-off was adverse; `1.0` the opposite. Unknown is
    a third thing."""
    c = L.cells(_ledger(5, []))[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_unknown"] == 5
    assert c["clean_rate"] is None
    assert c["usable_rate"] is None
    assert c["handoff_rate"] is None


def test_edited_counts_as_usable_but_not_as_clean():
    c = L.cells(_ledger(4, ["used-as-is", "edited", "rewrote", "discarded"]))[
        ("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["usable_rate"] == 0.5
    assert c["clean_rate"] == 0.25


def test_a_reviewed_use_does_not_count_toward_the_handoff_rate():
    """🔴 Review finding D1, which bites hand-off-first ranking specifically.

    Twenty outputs forwarded unread and twenty forwarded after thirty minutes of
    review each produce twenty `used-as-is` rows. DELEGATE means "you need not read
    it", so only `review_status` can bear on that claim."""
    unread = L.cells(_ledger(10, ["used-as-is"] * 10, review="none"))[
        ("omlx/Qwen3.8-27B-8bit", "E3")]
    reviewed = L.cells(_ledger(10, ["used-as-is"] * 10, review="performed"))[
        ("omlx/Qwen3.8-27B-8bit", "E3")]
    assert unread["clean_rate"] == reviewed["clean_rate"] == 1.0
    assert unread["handoff_rate"] == 1.0
    assert reviewed["handoff_rate"] == 0.0


def test_an_actor_report_does_not_count_toward_the_handoff_rate():
    """Review finding D3: a self-report is countable, never observed."""
    c = L.cells(_ledger(10, ["used-as-is"] * 10, source="actor_report"))[
        ("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["clean_rate"] == 1.0
    assert c["handoff_rate"] == 0.0
    assert c["sources"]["actor_report"] == 10
    assert c["sources"]["observed_operation"] == 0


def test_a_correction_revises_rather_than_adds_a_second_observation():
    """🔴 Review finding D5. Ten outputs re-marked `discarded` are ten observations
    with revised labels, not twenty."""
    rows = _ledger(10, ["used-as-is"] * 10)
    first_ids = [r["decision_id"] for r in rows if r["row"] == L.DISPOSITION]
    for did in first_ids:
        rows.append(_disp(decision_id=did, disposition="discarded",
                          review_status="none", supersedes="whatever"))
    c = L.cells(rows)[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_dispositions"] == 10, "a correction must not manufacture sample size"
    assert c["counts"]["discarded"] == 10
    assert c["counts"]["used-as-is"] == 0


def test_fanout_siblings_are_countable_as_one_batch():
    """Review finding T2: twenty near-identical jobs from one fan-out are not twenty
    independent experiences. Row count must not silently become evidence breadth."""
    c = L.cells(_ledger(20, ["used-as-is"] * 20, batch="fanout-1"))[
        ("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_dispositions"] == 20
    assert c["n_batches"] == 1


def test_a_launch_that_never_completed_is_counted_as_such():
    """🔴 Review finding L3, and the measured defect this row type exists for: a
    spawn returns a successful launch and then dies on HTTP 400 from the gateway.
    With only DECISION and DISPOSITION the launch IS the record."""
    rows = [_dec(), _att(status="launched")]
    c = L.cells(rows)[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_launched_never_completed"] == 1

    rows.append(_att(status="errored", error_class="invalid-model"))
    c = L.cells(rows)[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_launched_never_completed"] == 0
    assert c["errors"] == {"invalid-model": 1}


def test_rows_from_two_rule_versions_are_not_pooled():
    rows = _ledger(4, ["used-as-is"] * 4)
    stale = dict(rows[0])
    stale["rule_version"] = L.ACTUATION["version"] + 1
    stale["decision_id"] = "old"
    rows.append(stale)
    c = L.cells(rows)[("omlx/Qwen3.8-27B-8bit", "E3")]
    assert c["n_decisions"] == 4


# --- the actuation rule --------------------------------------------------------

def test_the_threshold_labels_a_cell_and_does_not_override_anything():
    """🔴 The precommitment is kept; the OVERRIDE is not built.

    Review finding T3: the prior holds benchmark percentiles, throughput and cost,
    and a used-as-is fraction is none of those. Until a mapping between them is
    defined, "empirical overrides prior" is not an executable rule.
    """
    assert L.ACTUATION["overrides_prior"] is False
    assert L.ACTUATION["min_dispositions"] == 20

    below = _ledger(19, ["used-as-is"] * 19)
    at = _ledger(20, ["used-as-is"] * 20)
    assert L.cell_basis(below, "omlx/Qwen3.8-27B-8bit", "E3") == ("provisional", 19)
    assert L.cell_basis(at, "omlx/Qwen3.8-27B-8bit", "E3") == ("empirical", 20)


def test_an_unrouted_cell_is_provisional_with_zero():
    assert L.cell_basis([], "omlx/anything", "E3") == ("provisional", 0)


def test_no_module_in_this_repo_reads_the_override_as_permission():
    """An allowlist is a claim and so is a disabled flag. If someone wires the
    override later, this is what notices -- and it must notice BEFORE the flag is
    flipped, because the flag flipping is the easy half."""
    import pathlib
    import re
    repo = pathlib.Path(L.__file__).resolve().parents[1]
    hits = []
    searched = 0
    for p in list((repo / "dispatchlib").rglob("*.py")) + \
            [q for q in (repo / "bin").iterdir() if q.is_file()]:
        # `ledger.py` declares the flag and the tests assert it is False; both are
        # legitimate reads. What must not exist is a CONSUMER that branches on it.
        if "archive" in p.parts or "tests" in p.parts or p.name == "ledger.py":
            continue
        searched += 1
        text = p.read_text(errors="ignore")
        if re.search(r"overrides_prior", text):
            hits.append(str(p.relative_to(repo)))
    # The router repo holds 6 modules plus bin/delegate.
    assert searched >= 6, "the glob found almost nothing; this test would pass vacuously"
    assert hits == [], f"{hits} reads ACTUATION['overrides_prior']; it is a label, not a gate"


# --- disagreements: chronology, not diagnosis ----------------------------------

def test_a_latency_miss_is_reported_without_a_cause():
    """🔴 Review finding L1. `predicted 4s / measured 40s` is produced both by a
    latency model that omitted long-input processing and by a request that queued
    behind other work. Separate row types give chronology, not causes."""
    rows = [_dec(predicted_secs=4.0), _att(latency_secs=40.0)]
    d = L.disagreements(rows)
    assert len(d) == 1
    assert d[0]["cause"] == "unresolved"
    assert d[0]["ratio"] == 10.0


def test_a_prediction_in_the_right_ballpark_is_not_a_disagreement():
    assert L.disagreements([_dec(predicted_secs=4.0), _att(latency_secs=5.0)]) == []


def test_a_missing_measurement_is_not_a_disagreement():
    """L6's shape: the decision predicted, the observation carries nothing. That is
    "actual unavailable", not agreement and not disagreement."""
    assert L.disagreements([_dec(predicted_secs=4.0), _att()]) == []
    assert L.disagreements([_dec(), _att(latency_secs=40.0)]) == []


# --- the decision id: a date format is a parser ------------------------------

def test_the_decision_id_carries_a_full_timestamp():
    """🔴 Caught by a real decision, not by a test: the first `_stamp` truncated every
    id to `202610`, because a negative UTC offset has no `+` and the `-0` it split on
    matches inside the DATE (`2026-10-01`). The result looked like an id."""
    did = L.decision_id("E3", "omlx/x", "2026-10-01T18:52:07-0700")
    stamp = did.split("-")[0]
    assert stamp == "20261001T185207", did
    assert did.startswith("20261001T185207-E3-")


def test_a_positive_offset_and_a_z_suffix_stamp_the_same_way():
    for ts in ("2026-10-01T18:52:07+0200", "2026-10-01T18:52:07Z",
               "2026-10-01T18:52:07.123456-0700"):
        assert L.decision_id("E3", "d", ts).startswith("20261001T185207-")


def test_two_decisions_in_the_same_second_still_differ():
    """A timestamp alone would not guarantee this, and the ids key three row types."""
    a = L.decision_id("E3", "omlx/x", "2026-10-01T18:52:07-0700")
    b = L.decision_id("E3", "omlx/y", "2026-10-01T18:52:07-0700")
    assert a != b
