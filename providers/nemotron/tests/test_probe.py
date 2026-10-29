"""The nemotron readiness probe, run as a subprocess so HOME and env are the real ones.

The probe must not import nemotron_bridge, so these tests never need openai either.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
import urllib.error

import pytest

PROBE = pathlib.Path(__file__).resolve().parent.parent / "bin" / "probe.py"
PLANTED = "nvapi-PLANTED-nemotron"


def run(home, *args, env_extra=None):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(PROBE), "--json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, json.loads(proc.stdout)


@pytest.fixture
def home(tmp_path):
    return tmp_path


def test_missing_key_is_not_ready_for_a_human(home):
    _, doc = run(home, "--offline")
    assert doc["contract"] == "dispatch-probe/1"
    assert doc["destination"] == "nemotron"
    assert doc["ready"] is False
    assert doc["fixable_by"] == "human"
    assert doc["facts"]["exposure_note"] == "external: NVIDIA cloud, public data only"


def test_offline_is_ready_null_and_makes_no_network_call(home, monkeypatch):
    # Run the probe in-process so the monkeypatch is in effect: any call fails loudly.
    import importlib.util

    monkeypatch.setenv("NVIDIA_API_KEY", PLANTED)

    def forbidden(*args, **kwargs):
        raise AssertionError("--offline must not touch the network")

    spec = importlib.util.spec_from_file_location("probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.urllib.request, "urlopen", forbidden)
    ready, _, _, _, facts = module.assess(offline=True)
    assert ready is None
    assert facts["http_status"] is None


def test_401_from_endpoint_is_not_ready_for_a_human(home):
    import importlib.util

    spec = importlib.util.spec_from_file_location("probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def rejected(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"{}"))

    import os

    os.environ["NVIDIA_API_KEY"] = PLANTED
    try:
        original = module.urllib.request.urlopen
        module.urllib.request.urlopen = rejected
        try:
            ready, why, remedy, fixable_by, facts = module.assess(offline=False)
        finally:
            module.urllib.request.urlopen = original
    finally:
        del os.environ["NVIDIA_API_KEY"]
    assert ready is False
    assert fixable_by == "human"
    assert facts["http_status"] == 401
    assert PLANTED not in json.dumps({"why": why, "remedy": remedy, "facts": facts})


def test_planted_key_never_reaches_stdout(home):
    nemo = home / ".config" / "nvidia"
    nemo.mkdir(parents=True)
    (nemo / "env").write_text(f"export NVIDIA_API_KEY={PLANTED}\n")
    out, doc = run(home, "--offline")
    assert doc["facts"]["key_source"] == str(nemo / "env")
    assert PLANTED not in out
