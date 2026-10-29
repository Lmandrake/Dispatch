#!/usr/bin/python3
"""Router readiness probe for the `nemotron` destination (contract dispatch-probe/1).

Does not import nemotron_bridge (it needs openai, which system python lacks). Prints
one JSON object and exits 0. The key is read, never printed. At most one GET, 8 s
timeout, status code only. Stdlib only, Python 3.9.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

CONTRACT = "dispatch-probe/1"
DESTINATION = "nemotron"
ENDPOINT = "https://integrate.api.nvidia.com/v1/models"
ENV_FILE = pathlib.Path.home() / ".config" / "nvidia" / "env"
KEY_NAMES = ("NVIDIA_API_KEY", "NGC_API_KEY")
TIMEOUT_S = 8
EXPOSURE_NOTE = "external: NVIDIA cloud, public data only"
REMEDY_NO_KEY = (
    "put NVIDIA_API_KEY=... (as `export NVIDIA_API_KEY=...`) in the NVIDIA env file"
)


def find_key():
    """Return (key, source), where source names where the key came from, never its value."""
    for name in KEY_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"env:{name}"
    if ENV_FILE.exists():
        pattern = re.compile(r"^\s*export\s+NVIDIA_API_KEY=(.*)$")
        for line in ENV_FILE.read_text(errors="replace").splitlines():
            match = pattern.match(line)
            if match:
                value = match.group(1).strip().strip("'\"")
                if value:
                    return value, str(ENV_FILE)
    return None, None


def probe_models(key):
    """One GET. Returns (http_status or None, models_offered or None)."""
    request = urllib.request.Request(ENDPOINT, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as raw:
            status = raw.status
            body = raw.read()
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # network, DNS, timeout: unknown, not "down"
        return None, None
    models = None
    if status == 200:
        try:
            data = json.loads(body).get("data")
            models = len(data) if isinstance(data, list) else None
        except (ValueError, AttributeError):
            models = None
    return status, models


def assess(offline):
    key, source = find_key()
    if key is None:
        return False, "no NVIDIA_API_KEY in the environment or the NVIDIA env file", REMEDY_NO_KEY, "human", {
            "key_source": None, "http_status": None, "models_offered": None,
        }
    if offline:
        return None, "key present; --offline, so the endpoint was not consulted", None, None, {
            "key_source": source, "http_status": None, "models_offered": None,
        }
    status, models = probe_models(key)
    facts = {"key_source": source, "http_status": status, "models_offered": models}
    if status == 200:
        return True, "NVIDIA endpoint accepted the key and listed models", None, None, facts
    if status in (401, 403):
        return False, f"NVIDIA endpoint rejected the key (HTTP {status})", (
            "the key in the NVIDIA env file is invalid or lacks access; replace it"
        ), "human", facts
    if status is None:
        why = "could not reach the NVIDIA endpoint within 8 s"
    else:
        why = f"NVIDIA endpoint answered HTTP {status}, which does not settle readiness"
    return None, why, None, None, facts


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="nemotron readiness probe (dispatch-probe/1)")
    parser.add_argument("--json", action="store_true", help="accepted; output is always JSON")
    parser.add_argument("--offline", action="store_true", help="make no network call")
    args = parser.parse_args(argv)
    try:
        ready, why, remedy, fixable_by, facts = assess(args.offline)
    except Exception as exc:  # the probe itself broke: say so, never guess
        ready, why, remedy, fixable_by = None, f"probe failed ({type(exc).__name__})", None, None
        facts = {"key_source": None, "http_status": None, "models_offered": None}
    facts["exposure_note"] = EXPOSURE_NOTE
    doc = {
        "contract": CONTRACT,
        "destination": DESTINATION,
        "ready": ready,
        "why": why,
        "remedy": remedy,
        "fixable_by": fixable_by,
        "facts": facts,
        "probed_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    sys.stdout.write(json.dumps(doc) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
