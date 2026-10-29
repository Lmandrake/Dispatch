import json, pathlib
from urllib.parse import urlparse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Default location, gitignored. Never commit real hostnames to this repo.
SANCTIONED_CONFIG = pathlib.Path("routing/sanctioned.local.json")


def load_sanctioned(path=SANCTIONED_CONFIG) -> list[str]:
    """Read sanctioned host suffixes from local config. A missing, malformed, or
    wrongly-typed config yields NO sanctioned suffixes -- absent or broken config
    must never widen access."""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("suffixes")
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, str) and s.strip().strip(".")]


def classify(target: str, endpoint: str,
             sanctioned_suffixes: list[str] | None = None) -> str:
    host = (urlparse(endpoint).hostname or "").lower().rstrip(".")
    if not host:
        return "remote"
    if target == "omlx" and host in LOOPBACK:
        return "local"
    for suffix in (sanctioned_suffixes or []):
        if not isinstance(suffix, str):
            continue
        bare = suffix.strip().lower().strip(".")
        if not bare:
            continue
        if host == bare or host.endswith("." + bare):
            return "sanctioned"
    return "remote"
