"""One gateway client for the 2026-10-20 model-ladder experiments.

Reads the model ids, base URL and credential helper from the environment Claude Code
is configured with (`capability._settings_env`); names no account. Every call is
appended to a JSONL cache keyed by (exp, item, arm, sample) so a rerun resumes rather
than re-pays. Cost is measured usage times the gateway's own `/model/info` price list,
fetched once per run -- never a remembered rate.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from dispatchlib import capability  # noqa: E402

import anthropic  # noqa: E402

STORE = pathlib.Path(os.environ.get("LADDER_STORE", "")) if os.environ.get("LADDER_STORE") \
    else pathlib.Path(os.environ.get("DISPATCH_STORAGE_ROOT")
                      or pathlib.Path.home() / ".cache" / "dispatch") / "ladder"
STORE.mkdir(parents=True, exist_ok=True)

_ENV = capability._settings_env()
_ROLE_KEY = {"haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
             "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
             "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL"}


def model_id(role: str) -> str:
    v = _ENV.get(_ROLE_KEY[role])
    if not v:
        raise SystemExit(f"{_ROLE_KEY[role]} is not set; refusing to guess a model id")
    return v.replace("[1m]", "")


_lock = threading.Lock()
_tok = {"v": None, "t": 0.0}


def _token() -> str:
    with _lock:
        if not _tok["v"] or time.time() - _tok["t"] > 1200:
            _tok["v"] = capability._api_key(_ENV)
            _tok["t"] = time.time()
            if not _tok["v"]:
                raise SystemExit("apiKeyHelper produced no token")
        return _tok["v"]


def client() -> anthropic.Anthropic:
    base = _ENV.get("ANTHROPIC_BASE_URL")
    if not base:
        raise SystemExit("ANTHROPIC_BASE_URL is not set")
    return anthropic.Anthropic(auth_token=_token(), base_url=base, max_retries=4,
                               timeout=900)


def prices() -> dict:
    """{model_id: (in $/tok, out $/tok)} from the gateway's own price list."""
    base = _ENV["ANTHROPIC_BASE_URL"].rstrip("/")
    req = urllib.request.Request(base + "/model/info",
                                 headers={"Authorization": "Bearer " + _token()})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    out = {}
    for m in data["data"]:
        mi = m.get("model_info") or {}
        if mi.get("input_cost_per_token") is not None:
            out[m["model_name"]] = (mi["input_cost_per_token"], mi["output_cost_per_token"])
    return out


_PRICES: dict | None = None


def cost(model: str, usage: dict) -> float:
    global _PRICES
    if _PRICES is None:
        _PRICES = prices()
    pin, pout = _PRICES[model]
    return usage["input_tokens"] * pin + usage["output_tokens"] * pout


def call(role: str, prompt: str, *, max_tokens: int = 32000, effort: str | None = None,
         system: str | None = None) -> dict:
    """One streamed call. Returns text, usage, cost, latency, ttft, stop_reason, served."""
    m = model_id(role)
    kw = {}
    if effort:
        kw["output_config"] = {"effort": effort}
    if system:
        kw["system"] = system
    t0 = time.time()
    ttft = None
    for attempt in range(4):
        try:
            with client().messages.stream(model=m, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": prompt}],
                                          **kw) as s:
                for ev in s:
                    if ttft is None and ev.type == "content_block_delta" \
                            and getattr(ev.delta, "type", "") == "text_delta":
                        ttft = time.time() - t0
                msg = s.get_final_message()
                served = s.response.headers.get("x-litellm-model-id")
            break
        except (anthropic.APIConnectionError, anthropic.InternalServerError,
                anthropic.RateLimitError) as e:
            if attempt == 3:
                return {"error": f"{type(e).__name__}: {e}"[:300], "role": role, "model": m}
            time.sleep(10 * (attempt + 1))
            t0 = time.time()
    text = "".join(b.text for b in msg.content if b.type == "text")
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
    return {"role": role, "model": m, "served": served, "text": text, "usage": usage,
            "cost": cost(m, usage), "latency": time.time() - t0, "ttft": ttft,
            "stop_reason": msg.stop_reason, "effort": effort}


class Cache:
    """Append-only JSONL of finished calls; `done` keys make a rerun resume."""

    def __init__(self, name: str):
        self.path = STORE / f"{name}.jsonl"
        self.rows = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r = json.loads(line)
                if "error" not in r:
                    self.rows[r["key"]] = r
        self._lock = threading.Lock()

    def get(self, key):
        return self.rows.get(key)

    def put(self, key, row):
        row = dict(row, key=key)
        with self._lock:
            with self.path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            if "error" not in row:
                self.rows[key] = row
        return row

    def spend(self) -> float:
        return sum(r.get("cost", 0) for r in self.rows.values())
