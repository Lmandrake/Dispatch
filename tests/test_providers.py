"""`$DISPATCH_PROVIDER_PATHS`: how Dispatch finds provider repos it does not contain."""
import json
import pathlib
import subprocess
import sys

from dispatchlib import providers

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_unset_searches_the_directory_beside_this_checkout():
    assert providers.search_dirs({}) == [REPO.parent]
    assert providers.search_dirs({providers.ENV: ""}) == [REPO.parent]


def test_first_listed_directory_holding_the_provider_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    (b / "EnterprisePlugin").mkdir(parents=True)
    (a / "Other").mkdir(parents=True)
    env = {providers.ENV: f"{a}:{b}"}
    assert providers.search_dirs(env) == [a, b]
    assert providers.find("EnterprisePlugin", env) == b / "EnterprisePlugin"


def test_a_provider_found_nowhere_is_none_not_an_error(tmp_path):
    assert providers.find("EnterprisePlugin", {providers.ENV: str(tmp_path)}) is None


def test_an_overlay_destination_whose_plugin_is_absent_reads_not_cloned(tmp_path):
    """A private plugin registered by the overlay must be optional: `where` still
    answers, and says the plugin is not cloned rather than failing."""
    ov = tmp_path / "ov" / "enterprise"
    ov.mkdir(parents=True)
    (ov / "overlay.json").write_text(json.dumps({"destinations": {"internal": {
        "kind": "consult", "exposure": "enterprise-internal", "ranked": False,
        "repo": "EnterprisePlugin", "skill": "x", "probe": ["bin/probe", "--json"],
        "for": "an on-prem enterprise model service"}}}))
    env = {"PATH": "/usr/bin:/bin", "HOME": str(pathlib.Path.home()),
           providers.ENV: str(tmp_path), providers.OVERLAY_ENV: str(tmp_path / "ov")}
    r = subprocess.run([sys.executable, str(REPO / "bin" / "delegate"), "where"],
                       capture_output=True, text=True, env=env, timeout=60)
    line = next((l for l in r.stdout.splitlines() if l.strip().startswith("internal")), "")
    assert "not cloned" in line, r.stdout + r.stderr


def test_overlay_absent_is_none_and_config_is_empty(tmp_path):
    env = {providers.OVERLAY_ENV: str(tmp_path)}
    assert providers.overlay("jev", env) is None
    assert providers.overlay_config("jev", env) == {}


def test_overlay_default_is_the_private_store_beside_the_provider_dirs(tmp_path):
    (tmp_path / "private-store" / providers.OVERLAY_REL / "jev").mkdir(parents=True)
    (tmp_path / "unrelated-repo").mkdir()
    env = {providers.ENV: str(tmp_path)}
    assert providers.overlay("jev", env) == (tmp_path / "private-store"
                                             / providers.OVERLAY_REL / "jev")


def test_a_broken_overlay_config_reads_as_empty_not_a_crash(tmp_path):
    (tmp_path / "jev").mkdir()
    (tmp_path / "jev" / "overlay.json").write_text("{not json")
    assert providers.overlay_config("jev", {providers.OVERLAY_ENV: str(tmp_path)}) == {}


def test_internal_hosts_come_from_the_overlay_only(tmp_path):
    from dispatchlib import capability as cap
    env = {providers.OVERLAY_ENV: str(tmp_path)}
    assert cap._static_internal_hosts(env) == {}
    (tmp_path / "enterprise").mkdir()
    (tmp_path / "enterprise" / "overlay.json").write_text('{"internal_hosts": {"a.example": "x"}}')
    assert cap._static_internal_hosts(env) == {"a.example": "x"}


def test_with_no_overlay_every_provider_reports_cleanly(tmp_path):
    """No private overlay and no sibling repos: `where` still answers, and nothing crashes."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           providers.ENV: str(tmp_path), providers.OVERLAY_ENV: str(tmp_path / "none")}
    r = subprocess.run([sys.executable, str(REPO / "bin" / "delegate"), "where"],
                       capture_output=True, text=True, env=env, timeout=90)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stdout + r.stderr
    for name in ("chatgpt", "jev", "nemotron"):
        assert any(l.strip().startswith(name) for l in r.stdout.splitlines()), name
