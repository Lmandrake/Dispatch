"""Effective settings.

Resolution order (later wins):
  1. svc/profiles/<profile>.py  SETTINGS dict  (profile chosen by SVC_PROFILE,
     else [service] profile in the ini, else "base")
  2. svc/config/service.ini      [network] / [service] sections
  3. environment variables       SVC_TIMEOUT, SVC_RETRIES, SVC_PORT
"""
import configparser
import os
import pathlib

from .profiles import PROFILES
from ._keys import INI_KEYS, ENV_KEYS, COERCE

CONFIG_DIR = pathlib.Path(__file__).parent / "config"


def _read_ini(path=None):
    cp = configparser.ConfigParser()
    cp.read(path or CONFIG_DIR / "service.ini")
    return cp


def load(env=None, ini_path=None):
    env = os.environ if env is None else env
    cp = _read_ini(ini_path)
    profile = env.get("SVC_PROFILE") or cp.get("service", "profile", fallback="base")
    eff = dict(PROFILES[profile].SETTINGS)
    for key, (section, option) in INI_KEYS.items():
        if cp.has_option(section, option):
            eff[key] = COERCE[key](cp.get(section, option))
    for key, var in ENV_KEYS.items():
        if var in env:
            eff[key] = COERCE[key](env[var])
    eff["profile"] = profile
    return eff
