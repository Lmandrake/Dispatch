import signal

import pytest

LIMIT_S = 30


@pytest.fixture(autouse=True)
def _wall_clock_limit():
    def boom(signum, frame):
        raise TimeoutError(f"test exceeded {LIMIT_S}s wall clock")
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(LIMIT_S)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLIS_CONFIG", str(tmp_path / "no-such-rc"))
    monkeypatch.delenv("TRELLIS_DB", raising=False)
    monkeypatch.delenv("TRELLIS_USER", raising=False)
    monkeypatch.setenv("TRELLIS_NOW", "2026-05-04T09:00:00Z")
