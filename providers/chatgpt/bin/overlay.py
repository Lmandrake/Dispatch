"""This provider's private overlay, when it runs inside Dispatch (providers/chatgpt).

Account pointers (the ChatGPT Project name, the consult ledger with its thread URLs, a
non-default Chrome profile) belong in a private overlay, found by Dispatch's
`dispatchlib/providers.py` (`$DISPATCH_OVERLAY`, else a private store beside the checkout).
Absent, or standalone outside Dispatch, every value falls back to a generic default and the
provider reports itself not configured where that matters. Never raises.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

NAME = "chatgpt"
_DISPATCH = pathlib.Path(__file__).resolve().parents[3]


def _providers():
    p = _DISPATCH / "dispatchlib" / "providers.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_dispatch_providers", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def directory() -> pathlib.Path | None:
    mod = _providers()
    try:
        return mod.overlay(NAME) if mod else None
    except Exception:
        return None


def config() -> dict:
    mod = _providers()
    try:
        return mod.overlay_config(NAME) if mod else {}
    except Exception:
        return {}


def value(key: str, default):
    v = config().get(key)
    return os.path.expanduser(v) if isinstance(v, str) and v.startswith("~") else (v or default)
