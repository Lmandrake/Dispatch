#!/usr/bin/python3
"""Router readiness probe for the `jev` destination (contract dispatch-probe/1).

Prints one JSON object and exits 0. Makes NO network call: a TypeSafe call is billed,
so a present key is reported as ready null, not checked. Never prints the key.
Stdlib only, Python 3.9.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys
import time

CONTRACT = "dispatch-probe/1"
DESTINATION = "jev"
REPO = pathlib.Path(__file__).resolve().parent.parent
REMEDY_NO_KEY = (
    "create a key at https://console.typesafe.ai/keys and put TYPESAFE_API_KEY=... "
    "in the consultjev env file"
)


def assess():
    """Return (ready, why, remedy, fixable_by, facts) without any network call."""
    sys.path.insert(0, str(REPO))
    from consultjev.client import JevError, credentials_path, load_api_key

    try:
        load_api_key()
    except JevError:
        return (
            False,
            "not configured: no TYPESAFE_API_KEY in the environment or in "
            f"{credentials_path()}",
            REMEDY_NO_KEY,
            "human",
            {"key_source": None},
        )
    source = "env" if os.environ.get("TYPESAFE_API_KEY") else str(credentials_path())
    return (
        None,
        "key present; validity is not checked because a TypeSafe call is billed",
        None,
        None,
        {"key_source": source},
    )


def emit(ready, why, remedy, fixable_by, facts, started):
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


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser(description="jev readiness probe (dispatch-probe/1)")
    parser.add_argument("--json", action="store_true", help="accepted; output is always JSON")
    parser.add_argument("--offline", action="store_true", help="accepted; this probe never calls out")
    parser.parse_args(argv)
    try:
        ready, why, remedy, fixable_by, facts = assess()
    except Exception as exc:  # the probe itself broke: say so, never guess
        ready, why, remedy, fixable_by, facts = (
            None,
            f"probe could not read the key ({type(exc).__name__})",
            None,
            None,
            {"key_source": None},
        )
    emit(ready, why, remedy, fixable_by, facts, started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
