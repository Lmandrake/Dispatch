"""The jev readiness probe, run as a subprocess so HOME and env are the real ones."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

PROBE = pathlib.Path(__file__).resolve().parent.parent / "bin" / "probe.py"
PLANTED = "sk-PLANTED-jev"


def run(home, env_key=None, overlay=None):
    # An explicit, empty overlay dir: the real private overlay must never leak into a test.
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin",
           "DISPATCH_OVERLAY": str(overlay or home / "no-overlay")}
    if env_key is not None:
        env["TYPESAFE_API_KEY"] = env_key
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, json.loads(proc.stdout)


@pytest.fixture
def home(tmp_path):
    return tmp_path


def test_key_in_env_is_ready_null_and_planted_key_never_printed(home):
    out, doc = run(home, env_key=PLANTED)
    assert doc["contract"] == "dispatch-probe/1"
    assert doc["destination"] == "jev"
    assert doc["ready"] is None
    assert doc["facts"]["key_source"] == "env"
    assert PLANTED not in out


def test_key_in_credentials_file_is_ready_null_and_file_is_named(home):
    cfg = home / ".config" / "consultjev"
    cfg.mkdir(parents=True)
    (cfg / "env").write_text(f"TYPESAFE_API_KEY={PLANTED}\n")
    out, doc = run(home)
    assert doc["ready"] is None
    assert doc["facts"]["key_source"] == str(cfg / "env")
    assert PLANTED not in out


def test_missing_key_is_ready_false_for_a_human(home):
    out, doc = run(home)
    assert doc["ready"] is False
    assert doc["fixable_by"] == "human"
    assert "console.typesafe.ai/keys" in doc["remedy"]
    assert "the consultjev env file" in doc["remedy"]



def test_overlay_names_the_key_file(home):
    over = home / "overlay"
    (over / "jev").mkdir(parents=True)
    keyfile = home / "elsewhere.env"
    keyfile.write_text(f"TYPESAFE_API_KEY={PLANTED}\n")
    (over / "jev" / "overlay.json").write_text(json.dumps({"credentials_file": str(keyfile)}))
    out, doc = run(home, overlay=over)
    assert doc["ready"] is None
    assert doc["facts"]["key_source"] == str(keyfile)
    assert PLANTED not in out


def test_no_overlay_and_no_key_reports_not_configured(home):
    out, doc = run(home)
    assert doc["ready"] is False
    assert "not configured" in doc["why"]
