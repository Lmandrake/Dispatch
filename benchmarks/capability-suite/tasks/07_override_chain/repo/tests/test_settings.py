from svc import settings
from svc.client import RelayClient


def test_env_override():
    cfg = settings.load(env={"SVC_TIMEOUT": "7"})
    assert cfg["timeout"] == 7


def test_client_uses_settings():
    c = RelayClient(settings.load(env={}))
    assert "timeout=" in c.describe()
