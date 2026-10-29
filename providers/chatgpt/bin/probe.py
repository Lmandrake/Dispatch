#!/usr/bin/env python3
"""Destination probe for ChatGPT consults (contract dispatch-probe/1; see ~/dev/Dispatch docs/PROBE_CONTRACT.md).

Answers one question for the router: can a consult be sent FROM the repo at --repo right now?
Prints exactly one JSON object with --json. Touches nothing: no file is written, no Chrome or
DevTools connection is opened, no daemon or container is started. Stdlib only, Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime

BIN = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))

# Importing consult has no side effects: it only defines constants and functions. Its
# is_enrolled() is NOT used, because state_dir() mkdirs .consult in the caller's repo.
import consult  # noqa: E402
import overlay as ov  # noqa: E402

CONTRACT = "dispatch-probe/1"
DESTINATION = "chatgpt"
PROFILE = "research"
ENROLL_CMD = f"python3 {BIN / 'consult.py'} --enroll"
PREFLIGHT_CMD = f"python3 {BIN / 'preflight.py'}"


def repo_root(path: str) -> pathlib.Path:
    """The git toplevel of path, as consult.project_root() resolves it; path itself if not a repo."""
    p = pathlib.Path(path).expanduser().resolve()
    try:
        out = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return pathlib.Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return p


def enrolled(root: pathlib.Path) -> bool:
    """Read-only mirror of consult.is_enrolled(root): same file, same key, no directory creation."""
    path = root / ".consult" / "config.json"
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text()).get("remote_consult"))
    except (ValueError, OSError, AttributeError):
        return False


def build(repo: str) -> dict:
    t0 = time.monotonic()
    root = repo_root(repo)
    is_enrolled = enrolled(root)
    provisioned = bool(consult.codex_provisioned(PROFILE))
    transport = "codex" if provisioned else "chrome"

    remedy = None
    fixable_by = None
    if not is_enrolled:
        ready = False
        why = "this repo is not enrolled for autonomous ChatGPT consults, so a consult from it would only be a draft"
        remedy = f"cd {root} && {ENROLL_CMD}"
        fixable_by = "agent"
    elif provisioned:
        ready = True
        why = ("codex transport is provisioned on this machine; whether its login is still valid is "
               "checked only by a real consult")
    else:
        ready = None
        why = "chrome transport; readiness needs bin/preflight.py, which may raise an Allow sheet"
        remedy = f"cd {root} && {PREFLIGHT_CMD}"

    return {
        "contract": CONTRACT,
        "destination": DESTINATION,
        "ready": ready,
        "why": why,
        "remedy": remedy,
        "fixable_by": fixable_by,
        "facts": {
            "repo": str(root),
            "enrolled": is_enrolled,
            "transport": transport,
            "codex_provisioned": provisioned,
            # The private overlay (account pointers, ledger) is optional: absent, the generic
            # defaults apply and consults still work from the user's own login.
            "overlay": "configured" if ov.directory() else "not configured",
        },
        "probed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - t0, 3),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the dispatch-probe/1 JSON object")
    ap.add_argument("--offline", action="store_true",
                    help="accepted for the contract; this probe makes no network call, so it changes nothing")
    ap.add_argument("--repo", default=".", help="the CALLER's repo root (default: cwd)")
    args = ap.parse_args(argv)

    result = build(args.repo)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"ready={result['ready']}: {result['why']}")
        if result["remedy"]:
            print(f"remedy: {result['remedy']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
