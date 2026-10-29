"""The seven tier rules, and the measurements each one is only as good as.

Two kinds of test. The DECISION tests pin what `tiers.decide` returns for each rule.
The EVIDENCE tests re-read the committed reports and fail if the direction a rule rests
on has stopped being true -- so a re-run that reversed a finding goes red here rather
than leaving a rule standing on a number that no longer says what it said. They pin
directions, never values (CLAUDE.md: pin properties, not data that is supposed to move).
"""
import pytest

from dispatchlib import tiers as T
from dispatchlib import ledger as L


# --- the decision ------------------------------------------------------------------

def test_rule1_no_check_means_no_haiku_for_any_kind():
    for k in T.KINDS:
        d = T.decide(k)
        assert d["model"] != T.HAIKU, k
        assert d["refused_haiku"], k


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_rule1_a_blank_check_is_no_check(blank):
    assert T.decide("code", check=blank)["model"] != T.HAIKU


def test_rule2_haiku_always_carries_its_escalation():
    d = T.decide("code", check="pytest -q")
    assert d["model"] == T.HAIKU
    assert d["tries"] == T.HAIKU_TRIES and d["escalate_to"] == T.OPUS
    assert 2 in d["rules"]


@pytest.mark.parametrize("kind", sorted(T.NEVER_HAIKU))
def test_rule3_never_haiku_kinds_refuse_even_with_a_check(kind):
    d = T.decide(kind, check="a model reads it and agrees")
    assert d["model"] == T.OPUS and 3 in d["rules"]


def test_rule3_the_never_list_covers_what_opus_wrongly_sent_to_haiku():
    """Opus sent factual recall to Haiku 9 of 9 times in the native-routing trial."""
    assert "recall" in T.NEVER_HAIKU


def test_rule4_high_stakes_is_opus_even_with_a_check():
    d = T.decide("code", check="pytest -q", stakes="high")
    assert d["model"] == T.OPUS and 4 in d["rules"]


def test_rule5_uncheckable_kinds_are_told_to_lower_effort_not_tier():
    d = T.decide("summary")
    assert d["model"] == T.OPUS and 5 in d["rules"]


def test_rule6_sonnet_only_for_well_specified_kinds_without_a_check():
    for k in T.KINDS:
        d = T.decide(k)
        if d["model"] == T.SONNET:
            assert k in T.SONNET_OK and (6 in d["rules"] or 8 in d["rules"])
    assert not (T.SONNET_OK & T.NEVER_HAIKU)
    assert T.SONNET_ONLY <= T.SONNET_OK
    assert T.SONNET_OK | T.NEVER_HAIKU | T.DETERMINISTIC == set(T.KINDS)


def test_rule7_asking_for_speed_never_changes_the_tier():
    for k in T.KINDS:
        for c in (None, "pytest"):
            assert T.decide(k, check=c, fast=True)["model"] == \
                T.decide(k, check=c)["model"]


def test_an_unknown_kind_is_refused_not_guessed():
    with pytest.raises(ValueError):
        T.decide("vibes")


def test_the_ledger_accepts_a_tier_decision_and_a_checked_attempt():
    L.check_row({"row": L.DECISION, "decision_id": "d", "task_kind": "spawn-code",
                 "destination": "tier/haiku", "machine": "m", "reason": "tier-rule",
                 "rejected": [{"destination": "tier/haiku", "why": "no-check"}],
                 "rule_version": L.ACTUATION["version"]})
    L.check_row({"row": L.ATTEMPT, "decision_id": "d", "status": "completed",
                 "check_passed": False, "rule_version": L.ACTUATION["version"]})
    with pytest.raises(L.LedgerRefused):
        L.check_row({"row": L.ATTEMPT, "decision_id": "d", "status": "completed",
                     "check_passed": "yes", "rule_version": L.ACTUATION["version"]})


# --- the evidence the rules stand on -----------------------------------------------

@pytest.fixture(scope="module")
def ev():
    return T.evidence()


def test_evidence_rule1_haiku_is_more_often_wrong_than_right_without_a_check(ev):
    c, w = ev["recall_haiku"]
    assert w > c
    assert ev["code_haiku_unchecked"][0] < ev["code_opus"][0]


def test_evidence_rule2_checked_haiku_is_no_worse_and_cheaper_than_opus(ev):
    c, usd, _ = ev["code_haiku_checked"][T.HAIKU_TRIES]
    assert c >= ev["code_opus"][0] - 0.02
    assert usd < 0.5 * ev["code_opus"][1]


def test_evidence_rule2_more_tries_than_chosen_buys_little(ev):
    k = ev["code_haiku_checked"]
    assert k[5][0] - k[T.HAIKU_TRIES][0] < 0.02


def test_evidence_rule3_confidence_cannot_rescue_recall(ev):
    escalated, _, cost_ratio = ev["recall_confidence_cascade"]
    assert escalated > 0.8 and cost_ratio > 0.9


def test_evidence_rule4_weaker_models_slip_more_errors_past_the_check(ev):
    fa = ev["code_false_accept"]
    assert fa["haiku"] > fa["opus"] > 0


def test_evidence_rule5_low_effort_opus_beats_dropping_a_tier(ev):
    assert ev["recall_opus_low_cost_ratio"] < 0.9
    assert ev["recall_opus_low_correct"] > ev["recall_sonnet"][0] + 0.1


def test_evidence_rule6_sonnet_is_close_on_code_and_cheaper(ev):
    assert ev["code_sonnet"][0] >= ev["code_opus"][0] - 0.03
    assert ev["code_sonnet"][1] < ev["code_opus"][1]


def test_evidence_rule7_haiku_is_not_meaningfully_faster_on_code(ev):
    lat = ev["code_median_latency"]
    assert lat["haiku"] >= 0.75 * lat["opus"]


def test_every_rule_has_an_evidence_line_that_renders():
    lines = T.evidence_lines(T.RULES)
    assert len(lines) == len(T.RULES) == 9
    assert all("evidence:" in ln for ln in lines)


@pytest.mark.parametrize("kind", sorted(T.SONNET_ONLY))
def test_rule8_agentic_and_draft_get_sonnet_even_with_a_check(kind):
    d = T.decide(kind, check="pytest -q")
    assert d["model"] == T.SONNET and 8 in d["rules"] and d["refused_haiku"]


def test_rule8_evidence_records_laguna_solver_result():
    line = T.evidence_lines([8])[0]
    assert "remote-118b" in line and "0 of 8" in line


# --- LODE-1: rule 0 (deterministic rung) and what counts as a mechanical check ------

def test_rule0_parseable_work_gets_no_model_even_with_a_check():
    for c in (None, "pytest -q"):
        d = T.decide("parse", check=c)
        assert d["model"] == T.PYTHON and 0 in d["rules"]


def test_rule0_high_stakes_does_not_promote_parse_to_a_model():
    assert T.decide("parse", stakes="high")["model"] == T.PYTHON


@pytest.mark.parametrize("check", ["python3 -m pytest -q", "jsonschema -i out.json s.json",
                                   "mypy src", "diff -q expected.txt out.txt",
                                   "tsc --noEmit"])
def test_mechanical_checks_are_accepted(check):
    assert T.is_mechanical(check)
    assert T.decide("code", check=check)["model"] == T.HAIKU


@pytest.mark.parametrize("check", ["opus reviews it", "a model reads it and agrees",
                                   "looks right", "haiku is confident", "LLM judge",
                                   "human review", "  "])
def test_a_reader_is_not_a_check_so_haiku_is_refused(check):
    d = T.decide("code", check=check)
    assert d["model"] == T.SONNET and d["refused_haiku"]
    assert not T.is_mechanical(check)


def test_tier_cli_prints_the_env_resolved_id_never_a_literal(capsys, monkeypatch):
    import importlib.machinery, importlib.util, pathlib
    from dispatchlib import capability as cap
    monkeypatch.setattr(cap, "_settings_env",
                        lambda: {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "fixture-haiku-id"})
    monkeypatch.setattr(cap, "proxy_rebind", lambda env=None: None)
    path = pathlib.Path(__file__).resolve().parents[1] / "bin" / "delegate"
    loader = importlib.machinery.SourceFileLoader("delegate_cli", str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    assert mod.main(["tier", "code", "--check", "pytest -q"]) == 0
    assert "resolves to: fixture-haiku-id" in capsys.readouterr().out
    monkeypatch.setattr(cap, "_settings_env", lambda: {})
    assert mod.main(["tier", "code"]) == 0
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL is not in the environment" in capsys.readouterr().out
    assert mod.main(["tier", "parse"]) == 0
    assert "no model" in capsys.readouterr().out
