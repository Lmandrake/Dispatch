import pathlib, sys, random, textwrap
R = pathlib.Path(sys.argv[1]); rnd = random.Random(7)
def w(rel, s):
    p = R / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(textwrap.dedent(s).lstrip())
w("conftest.py", "")
w("svc/__init__.py", '"""Telemetry relay service."""\n')
w("svc/constants.py", '''
    """Compile-time defaults. Most of these are overridden at runtime; see svc/settings.py."""
    DEFAULT_TIMEOUT = 30          # seconds; fallback only
    DEFAULT_RETRIES = 3
    DEFAULT_PORT = 8710
    MAX_PAYLOAD = 1 << 20
    POLL_INTERVAL = 5
    ''')
w("svc/profiles/__init__.py", '''
    from . import base, development, production

    PROFILES = {"base": base, "development": development, "production": production}
    ''')
w("svc/profiles/base.py", '''
    from ..constants import DEFAULT_TIMEOUT, DEFAULT_RETRIES, DEFAULT_PORT

    SETTINGS = {
        "timeout": DEFAULT_TIMEOUT,
        "retries": DEFAULT_RETRIES,
        "port": DEFAULT_PORT,
        "log_level": "INFO",
    }
    ''')
w("svc/profiles/development.py", '''
    from .base import SETTINGS as _BASE

    SETTINGS = {**_BASE, "log_level": "DEBUG", "timeout": 5}
    ''')
w("svc/profiles/production.py", '''
    from .base import SETTINGS as _BASE

    SETTINGS = {**_BASE, "retries": 5, "timeout": 60}
    ''')
w("svc/config/service.ini", '''
    ; Site configuration, layered on top of the active profile.
    [service]
    profile = production
    port = 8710

    [network]
    # connect/read timeout in seconds
    request_timeout = 25
    retries = 4
    ''')
w("svc/config/logging.ini", '''
    [logging]
    level = INFO
    timeout = 10
    ''')
w("svc/settings.py", '''
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
    ''')
w("svc/_keys.py", '''
    INI_KEYS = {
        "timeout": ("network", "request_timeout"),
        "retries": ("network", "retries"),
        "port": ("service", "port"),
    }
    ENV_KEYS = {"timeout": "SVC_TIMEOUT", "retries": "SVC_RETRIES", "port": "SVC_PORT"}
    COERCE = {"timeout": float, "retries": int, "port": int}
    ''')
w("svc/client.py", '''
    from . import settings


    class RelayClient:
        def __init__(self, cfg=None):
            cfg = cfg or settings.load()
            self.timeout = cfg["timeout"]
            self.retries = cfg["retries"]
            self.port = cfg["port"]

        def describe(self):
            return f"relay:{self.port} timeout={self.timeout:g}s retries={self.retries}"
    ''')
w("svc/healthcheck.py", '''
    HEALTHCHECK_TIMEOUT = 30  # independent of the relay timeout; do not couple


    def probe(fn):
        return fn(timeout=HEALTHCHECK_TIMEOUT)
    ''')
w("svc/cli.py", '''
    import sys
    from .client import RelayClient


    def main(argv=None):
        print(RelayClient().describe())
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    ''')
# filler modules mentioning timeout as distractors
names = ["codec", "framing", "metrics", "auth", "cache", "queue", "router", "schema", "storage", "throttle",
         "batch", "compress", "crc", "dedupe", "encoder", "filters", "handshake", "inbox", "journal", "keepalive",
         "ledger", "mux", "outbox", "parser", "replay", "sink", "tap"]
for n in names:
    k = rnd.randint(2, 90)
    extra = f"\n{n.upper()}_TIMEOUT = {k}  # local to {n}; unrelated to request timeout\n" if rnd.random() < 0.5 else ""
    w(f"svc/ext/{n}.py", f'''
        """{n} helpers."""
        {extra}

        def {n}_step(data, factor={rnd.randint(1,9)}):
            return [x * factor for x in data]
        ''')
w("svc/ext/__init__.py", "")
w("tests/test_settings.py", '''
    from svc import settings
    from svc.client import RelayClient


    def test_env_override():
        cfg = settings.load(env={"SVC_TIMEOUT": "7"})
        assert cfg["timeout"] == 7


    def test_client_uses_settings():
        c = RelayClient(settings.load(env={}))
        assert "timeout=" in c.describe()
    ''')
w("README.md", '''
    # relay

    Telemetry relay. Run `python3 -m svc.cli` to print the effective client configuration.
    ''')
