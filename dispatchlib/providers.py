"""Where Dispatch finds provider repos that live outside it (a private enterprise plugin, say).

`$DISPATCH_PROVIDER_PATHS` is a colon-separated list of directories; a provider named
`Foo` is the first `<dir>/Foo` that exists. Unset (or empty), the one directory searched
is the one holding this Dispatch checkout, so sibling clones are found with no
configuration and no home path is written into code. A provider found nowhere is
`None`: callers report it as not cloned, never as refused, and Dispatch runs without it.

PRIVATE OVERLAY. Account pointers, key-file locations, enterprise endpoints and consult
transcripts never live in this repo. `overlay(name)` finds a provider's private directory:
the first `<dir>/<name>` over `$DISPATCH_OVERLAY` (colon-separated) if set, else the first
`<d>/<store>/projects/Dispatch/providers/<name>` over the provider search dirs, where
`<store>` is any private checkout beside this one that holds that layout (sorted, first
wins). Absent, every provider reports "not configured" and Dispatch still runs. An overlay
holds pointers to secrets, never the secrets.
"""
from __future__ import annotations

import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
ENV = "DISPATCH_PROVIDER_PATHS"
OVERLAY_ENV = "DISPATCH_OVERLAY"
OVERLAY_REL = pathlib.Path("projects") / "Dispatch" / "providers"


def search_dirs(env: dict | None = None) -> list[pathlib.Path]:
    raw = (os.environ if env is None else env).get(ENV, "")
    dirs = [pathlib.Path(os.path.expanduser(d)) for d in raw.split(":") if d.strip()]
    return dirs or [REPO.parent]


def find(name: str, env: dict | None = None) -> pathlib.Path | None:
    for d in search_dirs(env):
        if (d / name).is_dir():
            return d / name
    return None


def overlay_dirs(env: dict | None = None) -> list[pathlib.Path]:
    """Where private overlays are looked for, in order."""
    env = os.environ if env is None else env
    raw = env.get(OVERLAY_ENV, "")
    dirs = [pathlib.Path(os.path.expanduser(d)) for d in raw.split(":") if d.strip()]
    if dirs:
        return dirs
    out = []
    for d in search_dirs(env):
        try:
            out += [s / OVERLAY_REL for s in sorted(d.iterdir()) if (s / OVERLAY_REL).is_dir()]
        except OSError:
            continue
    return out


def overlay(name: str, env: dict | None = None) -> pathlib.Path | None:
    """A provider's private overlay directory, or None when this machine has none."""
    for d in overlay_dirs(env):
        if (d / name).is_dir():
            return d / name
    return None


def overlay_config(name: str, env: dict | None = None) -> dict:
    """`<overlay>/<name>/overlay.json`, or {} when absent or unreadable. Never raises:
    a broken overlay must read as "not configured", not crash the router."""
    import json
    d = overlay(name, env)
    if d is None:
        return {}
    try:
        cfg = json.loads((d / "overlay.json").read_text())
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}
