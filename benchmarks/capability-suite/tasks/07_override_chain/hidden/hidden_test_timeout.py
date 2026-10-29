import pathlib
import subprocess
import sys

from svc import settings
from svc.client import RelayClient
from svc.constants import DEFAULT_TIMEOUT, DEFAULT_RETRIES, DEFAULT_PORT
from svc.healthcheck import HEALTHCHECK_TIMEOUT
from svc.profiles import PROFILES


def test_effective_timeout_is_45():
    cfg = settings.load(env={})
    assert float(cfg["timeout"]) == 45.0
    assert cfg["profile"] == "production"
    assert RelayClient(cfg).timeout == 45


def test_cli_reports_45():
    r = subprocess.run([sys.executable, "-m", "svc.cli"], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert "timeout=45s" in r.stdout


def test_env_override_still_wins():
    assert settings.load(env={"SVC_TIMEOUT": "7"})["timeout"] == 7
    assert settings.load(env={"SVC_TIMEOUT": "90.5"})["timeout"] == 90.5


def test_other_effective_values_unchanged():
    cfg = settings.load(env={})
    assert cfg["retries"] == 4
    assert cfg["port"] == 8710


def test_defaults_and_profiles_untouched():
    assert DEFAULT_TIMEOUT == 30 and DEFAULT_RETRIES == 3 and DEFAULT_PORT == 8710
    assert PROFILES["base"].SETTINGS["timeout"] == 30
    assert PROFILES["development"].SETTINGS["timeout"] == 5
    assert PROFILES["production"].SETTINGS["timeout"] == 60
    assert PROFILES["production"].SETTINGS["retries"] == 5
    assert HEALTHCHECK_TIMEOUT == 30


def test_ini_layer_still_generic(tmp_path):
    ini = tmp_path / "s.ini"
    ini.write_text("[service]\nprofile = development\n")
    cfg = settings.load(env={}, ini_path=ini)
    assert cfg["timeout"] == 5 and cfg["profile"] == "development"
    ini.write_text("[service]\nprofile = base\n[network]\nrequest_timeout = 12\n")
    assert settings.load(env={}, ini_path=ini)["timeout"] == 12
    ini.write_text("[service]\nprofile = production\n")
    assert settings.load(env={}, ini_path=ini)["timeout"] == 60
    assert settings.load(env={"SVC_PROFILE": "base"}, ini_path=ini)["timeout"] == 30


def test_logging_ini_untouched():
    text = (pathlib.Path(settings.__file__).parent / "config" / "logging.ini").read_text()
    assert "timeout = 10" in text
