"""What this machine can reach -- and, mostly, what the module refuses to claim.

Two groups of tests matter more than the rest:

  * **The declared-beats-probed rule is verified by proving NO SOCKET IS OPENED.**
    `tcp_open` is replaced with something that raises, so a probe that should not
    have happened fails loudly instead of merely being slow. A test that only checked
    the return value would pass on a correct answer reached the expensive way.

  * **Six fail-open paths, each named.** The guard's whole contract is that every
    uncertainty allows. Each uncertainty gets its own test, because a single
    "unknown allows" test would stop covering five of them without ever going red.

Several tests name a finding id from the cold design review
(`docs/ROUTER_CONSULT.md`) so a rule that was argued for is distinguishable from one
that was assumed.
"""
import json
import os
import pathlib
import time

import pytest

from dispatchlib import capability as cap

SERVED = ["region.anthropic.claude-opus-5", "region.anthropic.claude-sonnet-5",
          "region.anthropic.claude-sonnet-5-lb-1", "nova-pro"]
ENV = {"ANTHROPIC_BASE_URL": "https://gateway.example.com/sub-id-acct-a",
       "ANTHROPIC_DEFAULT_OPUS_MODEL": "region.anthropic.claude-opus-5[1m]",
       "ANTHROPIC_DEFAULT_SONNET_MODEL": "region.anthropic.claude-sonnet-5[1m]",
       "ANTHROPIC_DEFAULT_HAIKU_MODEL": "region.anthropic.claude-sonnet-5"}


def _snap(models=SERVED, known=True, machine=None, subscription="acct-a",
          ts=None, obs_ts=None):
    ts = time.time() if ts is None else ts
    obs_ts = ts if obs_ts is None else obs_ts
    return {"ts": ts, "machine": machine or cap.machine_key(),
            "subscription": subscription, "probed": True,
            "can_have_local_models": True,
            "gateway": {"value": {"models": models, "known": known,
                                  "source": "gateway", "error": None},
                        "ts": obs_ts, "failed": None}}


@pytest.fixture
def no_sockets(monkeypatch):
    """Any TCP connect is a test failure, not a slow path."""
    def _boom(*a, **k):
        raise AssertionError("a socket was opened where the declaration already "
                             "answered the question")
    monkeypatch.setattr(cap, "tcp_open", _boom)
    return _boom


def _declared_local(monkeypatch, key="desktop-a"):
    """Declare one local-model machine through the site config's env var."""
    monkeypatch.setenv(cap.LOCAL_MODEL_MACHINES_ENV, key)
    return key


def test_the_local_fleet_declaration_comes_from_config_not_code(monkeypatch):
    monkeypatch.setenv(cap.LOCAL_MODEL_MACHINES_ENV, " Desktop-A , other ")
    assert cap.local_model_machines() == {"desktop-a", "other"}
    monkeypatch.setenv(cap.LOCAL_MODEL_MACHINES_ENV, "")
    assert cap.local_model_machines() == frozenset()
    assert cap.can_have_local_models("desktop-a") is False


# --- machine identity ----------------------------------------------------------

def test_machine_key_honours_the_env_override(monkeypatch):
    monkeypatch.setenv("WAYPOINT_MACHINE", "LAPTOP-A")
    assert cap.machine_key() == "laptop-a"


def test_machine_key_strips_a_local_suffix_and_lowercases(monkeypatch):
    monkeypatch.delenv("WAYPOINT_MACHINE", raising=False)
    monkeypatch.setattr(cap.socket, "gethostname", lambda: "Workstation.local")
    assert cap.machine_key() == "workstation"


def test_an_explicit_override_beats_the_environment(monkeypatch):
    monkeypatch.setenv("WAYPOINT_MACHINE", "laptop-a")
    assert cap.machine_key("Other.Local") == "other"


def test_the_declared_local_fleet_matches_this_machine():
    """An allowlist is a CLAIM. `local_model_machines()` asserts which machines can
    serve local models, and the only one this test can check is the one it is running
    on -- so it checks that the declaration and the actual server agree HERE, in
    whichever direction they agree.

    This is the reverse guard CLAUDE.md requires for every exemption dict: without
    it, a re-image that changed the hostname would silently take the
    machine out of the local fleet and nothing would report it.
    """
    declared = cap.can_have_local_models()
    listening = cap.tcp_open("127.0.0.1", 8000, timeout=1.0)
    if listening:
        assert declared, (
            f"oMLX is listening on {cap.machine_key()} but that machine is not in "
            f"local_model_machines()={sorted(cap.local_model_machines())}; the "
            f"declaration would refuse every local route here")


# --- declared beats probed -----------------------------------------------------

def test_a_machine_that_cannot_have_local_models_is_not_probed(no_sockets):
    """🔴 The rule, verified by the absence of I/O rather than by the answer."""
    out = cap.local_models("laptop-a")
    assert out == {"possible": False, "listening": False, "models": [],
                   "known": True, "error": None}


def test_not_probed_is_known_not_unknown(no_sockets):
    """"This machine cannot have them" is KNOWLEDGE. Reporting `known: False` would
    make a caller treat a settled fact as a failure to look."""
    assert cap.local_models("laptop-a")["known"] is True


def test_a_declaration_does_not_assert_the_server_is_up(monkeypatch):
    """Review's narrowing of the rule: the declaration establishes where a
    destination BELONGS, never its current readiness."""
    monkeypatch.setattr(cap, "tcp_open", lambda *a, **k: False)
    out = cap.local_models(_declared_local(monkeypatch))
    assert out["possible"] is True and out["listening"] is False
    assert out["models"] == [] and out["known"] is True


def test_a_port_that_answers_but_will_not_list_is_unknown_not_empty(monkeypatch):
    """🔴 The masked-401 state. A plain curl of oMLX returns an HTTP 401 that a naive
    JSON read reports as "0 models served", and `routing/roster.json` lost every
    internal-endpoint row to exactly this. `known: False` is what stops an unreachable fleet
    reading as an empty one."""
    monkeypatch.setattr(cap, "tcp_open", lambda *a, **k: True)
    from dispatchlib.omlx import harness
    router = harness("router")
    monkeypatch.setattr(router, "served_model_ids",
                        lambda **k: (_ for _ in ()).throw(OSError("401")))
    out = cap.local_models(_declared_local(monkeypatch))
    assert out["listening"] is True
    assert out["known"] is False
    assert out["models"] == []
    assert "401" in out["error"]


def test_snapshot_without_probing_does_no_io(no_sockets):
    snap = cap.snapshot(machine="laptop-a", probe=False, write=False)
    assert snap["probed"] is False
    assert snap["enterprise"] is None and snap["local"] is None and snap["gateway"] is None


def test_an_empty_host_list_is_unknown_not_unreachable():
    assert cap.enterprise_reachable(hosts=[]) is None


# --- model resolution: the function the whole guard rests on -------------------

def test_an_alias_resolves_through_the_environment():
    assert cap.resolve_model("opus", ENV) == {
        "requested": "opus", "wire_id": "region.anthropic.claude-opus-5",
        "via": "alias"}


def test_haiku_resolves_to_sonnet_here_and_therefore_works():
    """🔴 With `ANTHROPIC_DEFAULT_HAIKU_MODEL` remapped to a Sonnet id, a
    `model: haiku` spawn works, so a "never pass model: haiku" rule would be STALE.

    A guard that hardcoded "block haiku" would block a valid spawn while letting the
    id that actually 400s through. Resolve first, then check the catalogue."""
    res = cap.resolve_model("haiku", ENV)
    assert res["wire_id"] == "region.anthropic.claude-sonnet-5"
    assert res["via"] == "alias"


def test_fable_is_expanded_by_the_harness_and_cannot_be_retargeted():
    """🔴 Measured once: a gateway answered
    `400 ... Invalid model name passed in model=claude-fable-5-1`
    for a `model: fable` spawn. No env key remaps it."""
    res = cap.resolve_model("fable", ENV)
    assert res["wire_id"] == "claude-fable-5-1"
    assert res["via"] == "harness-alias"
    assert "ANTHROPIC_DEFAULT_FABLE_MODEL" not in cap.ALIAS_ENV_KEYS.values()


def test_the_context_window_suffix_is_stripped():
    """The gateway's ids carry no `[`. A comparison that kept `[1m]` would find
    nothing and block every Opus spawn."""
    assert cap.resolve_model("region.anthropic.claude-opus-5[1m]", ENV)["wire_id"] \
        == "region.anthropic.claude-opus-5"


def test_no_model_named_is_a_distinct_answer():
    assert cap.resolve_model(None, ENV)["via"] == "default"
    assert cap.resolve_model("", ENV)["via"] == "default"


def test_the_active_subscription_comes_from_the_base_url():
    assert cap.active_subscription(ENV) == "acct-a"
    assert cap.active_subscription({"ANTHROPIC_BASE_URL": "https://x/y"}) is None
    assert cap.active_subscription({}) is None


# --- the snapshot cache --------------------------------------------------------

def test_a_fresh_snapshot_is_returned(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap()))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is not None


def test_a_stale_snapshot_is_none(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap(ts=time.time() - 10_000)))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is None


def test_a_snapshot_dated_in_the_future_is_stale_not_eternally_fresh(tmp_path,
                                                                    monkeypatch):
    """🔴 Review finding C5, and it was live: the first draft computed
    `now - ts > ttl` with no lower bound, so a clock that moved backwards -- or a
    snapshot copied from another machine -- pinned the cache permanently."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap(ts=time.time() + 86_400)))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is None


def test_a_small_clock_skew_is_tolerated(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap(ts=time.time() + 5)))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is not None


def test_a_snapshot_from_another_machine_is_refused(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap(machine="somebody-elses-mac")))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is None


def test_a_snapshot_for_another_subscription_is_refused(tmp_path, monkeypatch):
    """🔴 Review finding C1: freshness is not sufficiency. A five-second-old
    catalogue for account A says nothing about account B after a switch."""
    p = tmp_path / "s.json"
    p.write_text(json.dumps(_snap(subscription="acct-b", ts=time.time())))
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(p) is None


def test_a_malformed_or_missing_snapshot_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "_settings_env", lambda: ENV)
    assert cap.load_snapshot(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert cap.load_snapshot(bad) is None
    empty = tmp_path / "empty.json"
    empty.write_text("")
    assert cap.load_snapshot(empty) is None
    noto = tmp_path / "noto.json"
    noto.write_text('{"machine": "x"}')
    assert cap.load_snapshot(noto) is None


def test_a_stale_observation_inside_a_fresh_snapshot_is_unknown():
    """🔴 Review finding C2: refreshing one source must not rejuvenate another. A
    successful gateway refresh alongside a failed local refresh would otherwise carry
    the old fact forward under a brand-new top-level timestamp."""
    snap = _snap(ts=time.time(), obs_ts=time.time() - 10_000)
    assert cap.observation(snap, "gateway") is None
    assert cap.observation(_snap(), "gateway") is not None


def test_a_failed_observation_is_none_not_false():
    def _raises():
        raise RuntimeError("boom")
    obs = cap._observe(_raises)
    assert obs["value"] is None
    assert obs["failed"] == "RuntimeError"


def test_one_failed_probe_does_not_erase_the_others(monkeypatch):
    """Review finding C4: one discovery failure must not disable every guard."""
    monkeypatch.setattr(cap, "enterprise_reachable",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(cap, "gateway_catalogue",
                        lambda *a, **k: {"models": SERVED, "known": True,
                                         "source": "gateway", "error": None})
    monkeypatch.setattr(cap, "local_models",
                        lambda *a, **k: {"possible": False, "listening": False,
                                         "models": [], "known": True, "error": None})
    snap = cap.snapshot(machine="laptop-a", write=False)
    assert snap["enterprise"]["failed"] == "OSError"
    assert cap.observation(snap, "gateway")["models"] == SERVED


# --- the guard: one test per fail-open path ------------------------------------

def test_an_unserved_model_blocks_and_names_a_served_one():
    v = cap.hook_verdict("fable", snap=_snap(), env=ENV)
    assert v["action"] == cap.BLOCK
    assert v["wire_id"] == "claude-fable-5-1"
    assert "claude-fable-5-1" in v["reason"]
    assert "AFTER the agent launches" in v["reason"]
    assert v["suggest"] in SERVED


def test_a_served_model_passes():
    assert cap.hook_verdict("opus", snap=_snap(), env=ENV)["action"] == cap.ALLOW
    assert cap.hook_verdict("haiku", snap=_snap(), env=ENV)["action"] == cap.ALLOW


def test_the_guard_never_rewrites_the_model():
    """🔴 A silent substitution is what makes a ladder unauditable, which is the
    disease this component treats: five prose ladders drifted undetected precisely
    because nothing ever reported a correction. The guard NAMES and BLOCKS."""
    v = cap.hook_verdict("fable", snap=_snap(), env=ENV)
    assert v["action"] == cap.BLOCK
    assert v["wire_id"] == "claude-fable-5-1", "the requested id must survive intact"
    assert v["suggest"] != v["wire_id"]


def test_fail_open_1_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "load_snapshot", lambda **k: None)
    assert cap.hook_verdict("fable", env=ENV)["action"] == cap.ALLOW


def test_fail_open_2_a_catalogue_that_could_not_be_read():
    snap = _snap(models=[], known=False)
    assert cap.hook_verdict("fable", snap=snap, env=ENV)["action"] == cap.ALLOW


def test_fail_open_3_an_empty_catalogue():
    """An empty served list is not evidence the model is absent -- it is evidence
    nothing was learned. Blocking on it would refuse every spawn."""
    snap = _snap(models=[], known=True)
    assert cap.hook_verdict("fable", snap=snap, env=ENV)["action"] == cap.ALLOW


def test_fail_open_4_an_alias_with_no_mapping():
    env = dict(ENV)
    del env["ANTHROPIC_DEFAULT_HAIKU_MODEL"]
    v = cap.hook_verdict("haiku", snap=_snap(), env=env)
    assert v["action"] == cap.ALLOW
    assert v["wire_id"] is None


def test_fail_open_5_no_model_named():
    """`via: default` means the call named nothing, so an agent definition or the
    session default decides -- and the harness's precedence between those has changed
    across versions (review finding A1). Unknown, therefore allowed."""
    v = cap.hook_verdict(None, snap=_snap(), env=ENV)
    assert v["action"] == cap.ALLOW
    assert v["via"] == "default"


def test_fail_open_6_a_stale_observation(monkeypatch):
    snap = _snap(obs_ts=time.time() - 10_000)
    assert cap.hook_verdict("fable", snap=snap, env=ENV)["action"] == cap.ALLOW


def test_an_allow_carries_no_reason():
    """A reason on an allow would be printed by a caller that only checks for text."""
    assert cap.hook_verdict("opus", snap=_snap(), env=ENV)["reason"] == ""


def test_the_suggestion_is_a_plain_id_not_a_load_balanced_alias():
    v = cap.hook_verdict("fable", snap=_snap(), env=ENV)
    assert "-lb-" not in v["suggest"] and "load-balanced" not in v["suggest"]


def test_there_is_no_suggestion_when_nothing_recognisable_is_served():
    snap = _snap(models=["weird-thing-1"])
    v = cap.hook_verdict("fable", snap=snap, env=ENV)
    assert v["action"] == cap.BLOCK
    assert v["suggest"] == "weird-thing-1"
    assert "Use" in v["reason"]


# --- the catalogue read: four-case calibration ---------------------------------

def test_gateway_with_no_base_url_is_unknown_not_empty():
    out = cap.gateway_catalogue({})
    assert out["known"] is False
    assert out["models"] == []
    assert "ANTHROPIC_BASE_URL" in out["error"]


def test_gateway_falls_back_to_the_cache_and_says_so(monkeypatch):
    monkeypatch.setattr(cap, "_api_key", lambda env: None)
    monkeypatch.setattr(cap, "_cached_catalogue", lambda sub: ["cached-model"])
    out = cap.gateway_catalogue(ENV)
    assert out["known"] is False, "a cache read is never 'known'"
    assert out["models"] == ["cached-model"]
    assert out["source"] == "cache"
    assert "no API key" in out["error"]


def test_gateway_with_neither_live_nor_cache_names_no_source(monkeypatch):
    monkeypatch.setattr(cap, "_api_key", lambda env: None)
    monkeypatch.setattr(cap, "_cached_catalogue", lambda sub: [])
    out = cap.gateway_catalogue(ENV)
    assert out["known"] is False and out["source"] is None


def test_the_cached_catalogue_never_raises(tmp_path, monkeypatch):
    assert cap._cached_catalogue(None) == []
    assert cap._cached_catalogue("no-such-account-anywhere") == []


# --- consult readiness ---------------------------------------------------------

# Readiness now comes from each destination repo's own probe (docs/PROBE_CONTRACT.md).
# These tests pin how the ROUTER reads a probe; each repo pins its own probe's logic.

def _fake_repo(tmp_path, name, body):
    repo = tmp_path / name
    (repo / "bin").mkdir(parents=True)
    (repo / "bin" / "probe.py").write_text(body)
    return repo


def _registry(tmp_path, specs):
    reg = tmp_path / "destinations.json"
    reg.write_text(json.dumps({"destinations": specs}))
    return reg


def _emit(ready, contract="dispatch-probe/1"):
    return ("import json,sys\n"
            f"print(json.dumps({{'contract': {contract!r}, 'destination': 'x', "
            f"'ready': {ready!r}, 'why': 'w', 'remedy': None, 'fixable_by': None, "
            f"'facts': {{'offline': '--offline' in sys.argv, 'argv': sys.argv[1:]}}}}))\n")


def test_a_probe_answer_is_read_three_valued(tmp_path):
    specs = {}
    for name, ready in (("t", True), ("f", False), ("n", None)):
        repo = _fake_repo(tmp_path, name, _emit(ready))
        specs[name] = {"kind": "consult", "exposure": "external", "repo": str(repo),
                       "probe": ["bin/probe.py", "--json"]}
    got = cap.consults(registry=_registry(tmp_path, specs))
    assert len(got) == 3, "the registry was read as empty"
    assert got["t"]["ready"] is True
    assert got["f"]["ready"] is False
    assert got["n"]["ready"] is None
    assert got["t"]["exposure"] == "external"


@pytest.mark.parametrize("body,needle", [
    ("import sys; sys.exit(3)", "exited 3"),
    ("print('not json')", "not JSON"),
    (_emit(True, contract="something-else"), "does not speak"),
    (_emit("yes"), "three-valued"),
    ("import time; time.sleep(5)", "did not answer"),
])
def test_every_way_a_probe_can_fail_is_unknown_never_refused(tmp_path, body, needle):
    """A broken probe has not established that the destination is down."""
    repo = _fake_repo(tmp_path, "d", body)
    got = cap.run_probe("d", {"repo": str(repo), "probe": ["bin/probe.py", "--json"]},
                        timeout=1.0)
    assert got["ready"] is None
    assert needle in got["why"]


def test_an_uncloned_repo_or_missing_probe_is_unknown(tmp_path):
    got = cap.run_probe("d", {"repo": str(tmp_path / "nope"), "probe": ["bin/probe.py"]})
    assert got["ready"] is None and "not cloned" in got["why"]
    (tmp_path / "old").mkdir()
    got = cap.run_probe("d", {"repo": str(tmp_path / "old"), "probe": ["bin/probe.py"]})
    assert got["ready"] is None and "predates the probe contract" in got["why"]


def test_verify_false_tells_every_probe_to_stay_offline(tmp_path):
    repo = _fake_repo(tmp_path, "d", _emit(None))
    reg = _registry(tmp_path, {"d": {"repo": str(repo), "probe": ["bin/probe.py"]}})
    assert cap.consults(verify=False, registry=reg)["d"]["facts"]["offline"] is True
    assert cap.consults(verify=True, registry=reg)["d"]["facts"]["offline"] is False


def test_chatgpt_readiness_is_asked_about_the_callers_repo(tmp_path):
    """🔴 The P1 defect: the router used to read ITS OWN enrollment for every caller."""
    repo = _fake_repo(tmp_path, "d", _emit(True))
    caller = tmp_path / "some-other-project"
    caller.mkdir()
    got = cap.run_probe("d", {"repo": str(repo),
                              "probe": ["bin/probe.py", "--repo", "{caller}"]},
                        caller=caller)
    assert got["facts"]["argv"] == ["--repo", str(caller)]


def test_a_missing_registry_raises_rather_than_reading_as_no_destinations(tmp_path):
    with pytest.raises(Exception):
        cap.consults(registry=tmp_path / "absent.json")


def test_the_real_registry_names_a_probe_that_exists_in_every_cloned_repo():
    """The registry is a claim about the destination repos. Check it against them.
    Four are public and committed; the overlay may add private ones."""
    reg = cap.destinations()
    assert len(reg) >= 4
    checked = 0
    for name, spec in reg.items():
        assert spec["exposure"] in ("on-machine", "enterprise-internal", "gateway", "external")
        repo = cap.repo_path(spec)
        if repo.is_dir():
            assert (repo / spec["probe"][0]).exists(), f"{name}: {spec['probe'][0]} missing"
            checked += 1
    assert checked >= 1, "no destination repo is cloned here, so nothing was checked"


def test_a_loopback_base_url_is_reported_as_a_proxy_rebind():
    assert cap.proxy_rebind({"ANTHROPIC_BASE_URL": "http://localhost:4000"})
    assert cap.proxy_rebind({"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000/v1"})
    assert cap.proxy_rebind({"ANTHROPIC_BASE_URL": "https://gateway.example.org"}) is None
    assert cap.proxy_rebind({}) is None


# --- alias collapse: a ladder rung that is not a different model ---------------

def test_two_aliases_pointing_at_one_model_are_reported():
    """🔴 Escalation ladders are usually written in aliases and retries one
    rung up. A collapsed rung re-runs the same weights, so the retry that was meant
    to try something stronger tries the same thing and fails the same way."""
    env = {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "region.anthropic.claude-sonnet-5",
           "ANTHROPIC_DEFAULT_SONNET_MODEL": "region.anthropic.claude-sonnet-5[1m]",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "region.anthropic.claude-opus-5[1m]"}
    assert cap.alias_collapse(env) == {
        "region.anthropic.claude-sonnet-5": ["haiku", "sonnet"]}


def test_the_context_suffix_does_not_hide_a_collapse():
    """`...sonnet-5` and `...sonnet-5[1m]` are the same weights with a different
    context window. Comparing the unstripped strings would call them two models and
    report a healthy ladder."""
    env = {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "m",
           "ANTHROPIC_DEFAULT_SONNET_MODEL": "m[1m]",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "n"}
    assert cap.alias_collapse(env) == {"m": ["haiku", "sonnet"]}


def test_a_distinct_ladder_reports_nothing():
    env = {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "a",
           "ANTHROPIC_DEFAULT_SONNET_MODEL": "b",
           "ANTHROPIC_DEFAULT_OPUS_MODEL": "c"}
    assert cap.alias_collapse(env) == {}


def test_an_unmapped_alias_is_omitted_not_grouped_under_none():
    """Two aliases with no mapping are both unknown, not 'the same model'."""
    assert cap.alias_collapse({"ANTHROPIC_DEFAULT_OPUS_MODEL": "a"}) == {}


def test_the_live_environment_is_reported_as_it_actually_is():
    """The reverse guard: an allowlist is a claim and so is a clean report. This
    asserts the function agrees with the real environment rather than with the
    fixture above -- the failure mode it is written against is a correct function
    reading the wrong place.

    It does NOT assert the ladder is healthy: a remapped haiku rung can collapse onto
    the sonnet rung. Whether to fix that is a policy decision, not this test's business.
    """
    env = cap._settings_env()
    if not any(env.get(k) for k in cap.ALIAS_ENV_KEYS.values()):
        pytest.skip("no Claude Code model environment on this machine (a bare clone or CI)")
    live = cap.alias_collapse()
    for wire, aliases in live.items():
        for a in aliases:
            assert cap.resolve_model(a, env)["wire_id"] == wire
    distinct = {cap.resolve_model(a, env)["wire_id"] for a in cap.ALIAS_ENV_KEYS
                if cap.resolve_model(a, env)["wire_id"]}
    assert len(distinct) >= 1, "no alias resolves at all; the env read is broken"


