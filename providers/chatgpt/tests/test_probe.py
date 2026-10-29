"""Tests for bin/probe.py (dispatch-probe/1). No network, no Chrome, no files written in the repo probed."""
import json
import os
import pathlib
import socket
import subprocess
import sys

import pytest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))
import probe  # noqa: E402

CONTRACT_KEYS = {"contract", "destination", "ready", "why", "remedy", "fixable_by",
                 "facts", "probed_at", "elapsed_s"}
FACT_KEYS = {"repo", "enrolled", "transport", "codex_provisioned", "overlay"}


def _enroll(root: pathlib.Path, extra=None):
    d = root / ".consult"
    d.mkdir(parents=True, exist_ok=True)
    data = {"remote_consult": True}
    data.update(extra or {})
    (d / "config.json").write_text(json.dumps(data))


def _listing(root: pathlib.Path):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


@pytest.fixture
def provisioned(monkeypatch):
    def set_value(value):
        monkeypatch.setattr(probe.consult, "codex_provisioned", lambda profile: value)
    return set_value


def test_output_has_every_contract_key(tmp_path, provisioned):
    provisioned(True)
    out = probe.build(str(tmp_path))
    assert set(out) == CONTRACT_KEYS
    assert out["contract"] == "dispatch-probe/1"
    assert out["destination"] == "chatgpt"
    assert set(out["facts"]) == FACT_KEYS
    assert out["facts"]["repo"] == str(tmp_path.resolve())


def test_unenrolled_repo_is_not_ready_and_agent_fixable(tmp_path, provisioned):
    provisioned(True)
    out = probe.build(str(tmp_path))
    assert out["ready"] is False
    assert out["fixable_by"] == "agent"
    assert "--enroll" in out["remedy"]
    assert out["facts"]["enrolled"] is False


def test_enrolled_with_codex_is_ready(tmp_path, provisioned):
    _enroll(tmp_path)
    provisioned(True)
    out = probe.build(str(tmp_path))
    assert out["ready"] is True
    assert out["facts"]["transport"] == "codex"
    assert out["remedy"] is None and out["fixable_by"] is None


def test_enrolled_without_codex_is_null_chrome(tmp_path, provisioned):
    _enroll(tmp_path)
    provisioned(False)
    out = probe.build(str(tmp_path))
    assert out["ready"] is None
    assert out["facts"]["transport"] == "chrome"
    assert out["fixable_by"] is None
    assert "bin/preflight.py" in out["why"]


def test_probe_creates_no_files_in_the_repo(tmp_path, provisioned):
    unenrolled = tmp_path / "bare"
    unenrolled.mkdir()
    enrolled_repo = tmp_path / "enrolled"
    enrolled_repo.mkdir()
    _enroll(enrolled_repo)
    for repo in (unenrolled, enrolled_repo):
        for flag in (True, False):
            provisioned(flag)
            before = _listing(repo)
            probe.build(str(repo))
            assert _listing(repo) == before, (repo, flag)
    assert not (unenrolled / ".consult").exists()


def test_probe_never_connects_to_the_network(tmp_path, provisioned, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("probe opened a socket")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    _enroll(tmp_path)
    provisioned(False)
    assert probe.build(str(tmp_path))["ready"] is None


def test_planted_secret_never_reaches_stdout(tmp_path, provisioned, capsys):
    fake = "sk-FAKE-PLANTED-0000-DO-NOT-PRINT"
    _enroll(tmp_path, extra={"api_key": fake})
    provisioned(True)
    assert probe.main(["--json", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert fake not in out
    assert json.loads(out)["ready"] is True


def test_cli_json_parses_under_a_subprocess(tmp_path):
    result = subprocess.run([sys.executable, str(BIN / "probe.py"), "--json", "--repo", str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    obj = json.loads(result.stdout)
    assert set(obj) == CONTRACT_KEYS
    assert obj["ready"] is False



def test_probe_without_an_overlay_says_not_configured_and_does_not_crash(tmp_path):
    env = dict(os.environ, DISPATCH_OVERLAY=str(tmp_path / "none"))
    r = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve().parents[1] / "bin" / "probe.py"),
                        "--json", "--repo", str(tmp_path)], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["facts"]["overlay"] == "not configured"
    assert doc["ready"] in (True, False, None)
