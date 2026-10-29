import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRELLIS_CONFIG", str(tmp_path / "no-such-rc"))
    monkeypatch.delenv("TRELLIS_DB", raising=False)
    monkeypatch.delenv("TRELLIS_USER", raising=False)
    monkeypatch.setenv("TRELLIS_NOW", "2026-05-01T09:00:00Z")


@pytest.fixture(params=["json", "sqlite"])
def backend(request):
    return request.param
