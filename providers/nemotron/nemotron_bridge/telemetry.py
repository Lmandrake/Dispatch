"""Model behaviour ledger: every API call is a free observation. Keep them.

The assessment harness answers "how good is this model" from a battery run. It
has never answered "can I reach it right now, and how has it behaved lately" —
so that got re-derived from a single fresh sample each time, which is not enough
to tell *gone* from *busy*. On 2026-08-26 the same model returned 404, then a
clean answer, then 404 again within seconds; `kimi-k3` answered 1 call in 12
while `nemotron-3-super` answered 24/24 in the same loop.

Every call already made through `NemotronClient` is evidence about that. This
module records them append-only and rolls them into behaviour profiles: uptime
over recent windows, error-code mix, latency distribution, and a verdict that
separates terminal states (410 end-of-life, sustained 404) from transient ones
(429 capacity, 500, timeout).

Design constraints that shaped this:

* **Recording must never break a call.** Every write is best-effort and
  swallows its own exceptions. Telemetry that can fail a run is worse than none.
* **Append-only, one line per observation.** Safe for concurrent `nemo`
  processes; no read-modify-write window to lose data in.
* **Sharded per machine.** A repo synced between machines over a shared folder
  does not merge concurrent edits — it silently forks the file into
  "conflicted copy" duplicates. Two machines appending to one ledger would lose
  data. Each writes `obs-<host>.jsonl`; the reader unions every shard, so
  profiles get both machines' coverage for free.
* **Raw ledger is derived data.** It is gitignored; the rolled-up profile is
  what gets committed, per the repo's "provenance not bulk" rule.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config

LEDGER_DIR = config.RESULTS_DIR / "telemetry"
PROFILE_PATH = LEDGER_DIR / "profiles.md"
PROFILE_JSON = LEDGER_DIR / "profiles.json"

# Disable with NEMO_TELEMETRY=0 (e.g. in a benchmark you do not want recorded).
ENABLED = os.environ.get("NEMO_TELEMETRY", "1") != "0"

_HOST = re.sub(r"[^A-Za-z0-9_-]+", "-", socket.gethostname() or "unknown")[:40]


def shard_path() -> Path:
    return LEDGER_DIR / f"obs-{_HOST}.jsonl"


# --------------------------------------------------------------------------
# Error taxonomy
# --------------------------------------------------------------------------
#
# The distinction that matters is terminal vs transient. A 410 is a stated
# end-of-life and will never recover; a 429 means try again later. Treating
# them alike is what produced a "47 models unavailable" census that cannot be
# trusted.

TERMINAL = {"eol_410", "gone_404"}
TRANSIENT = {"rate_429", "server_5xx", "timeout", "connection", "overloaded"}


def classify(ok: bool, error: str | None) -> str:
    if ok:
        return "ok"
    e = (error or "")
    low = e.lower()
    if "410" in e or "end of life" in low:
        return "eol_410"
    if "404" in e or "not found" in low:
        return "gone_404"
    if "ratelimit" in low.replace(" ", "") or "429" in e:
        return "rate_429"
    if "overloaded" in low or "temporarily" in low:
        return "overloaded"
    if "timeout" in low or "timedout" in low:
        return "timeout"
    if "connection" in low:
        return "connection"
    if re.search(r"\b5\d\d\b", e) or "internalserver" in low.replace(" ", ""):
        return "server_5xx"
    return "other"


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def record(
    model: str,
    ok: bool,
    error: str | None = None,
    latency: float | None = None,
    ttft: float | None = None,
    completion_tokens: int | None = None,
    kind: str = "chat",
    tools: bool = False,
) -> None:
    """Append one observation. Best-effort: never raises, never blocks a call."""
    if not ENABLED:
        return
    try:
        obs = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "kind": kind,
            "tools": bool(tools),
            "ok": bool(ok),
            "class": classify(ok, error),
            "latency": round(latency, 3) if latency is not None else None,
            "ttft": round(ttft, 3) if ttft is not None else None,
            "tokens": completion_tokens,
            "host": _HOST,
        }
        if not ok and error:
            obs["error"] = error[:300]
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        with shard_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obs) + "\n")
    except Exception:
        pass  # telemetry must never break the caller


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def load(models: list[str] | None = None) -> list[dict]:
    """Union every machine's shard. Tolerates partial/corrupt trailing lines."""
    out: list[dict] = []
    if not LEDGER_DIR.exists():
        return out
    want = set(models) if models else None
    for shard in sorted(LEDGER_DIR.glob("obs-*.jsonl")):
        try:
            for line in shard.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn write from a concurrent process
                if want is None or o.get("model") in want:
                    out.append(o)
        except OSError:
            continue
    out.sort(key=lambda o: o.get("ts", ""))
    return out


def _age_hours(ts: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except Exception:
        return 1e9


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return round(s[i], 3)


WINDOWS = [("1h", 1), ("24h", 24), ("7d", 168)]


def profile(model: str, obs: list[dict], now: datetime | None = None) -> dict:
    """Behaviour profile for one model from its observations."""
    now = now or datetime.now(timezone.utc)
    mine = [o for o in obs if o.get("model") == model]
    if not mine:
        return {"model": model, "observations": 0, "verdict": "unobserved"}

    aged = [(o, _age_hours(o.get("ts", ""), now)) for o in mine]
    uptime = {}
    for label, hours in WINDOWS:
        win = [o for o, a in aged if a <= hours]
        uptime[label] = {
            "n": len(win),
            "ok_pct": round(100 * sum(1 for o in win if o["ok"]) / len(win)) if win else None,
        }

    lat = [o["latency"] for o in mine if o.get("ok") and o.get("latency")]
    ttfts = [o["ttft"] for o in mine if o.get("ok") and o.get("ttft")]
    classes = Counter(o.get("class", "other") for o in mine if not o.get("ok"))
    ok_all = [o for o in mine if o["ok"]]
    last_ok = ok_all[-1]["ts"] if ok_all else None

    # Tool-calling is a separate capability: a model can answer plain chat and
    # reject tools=. Track the two request shapes apart so one cannot mask the other.
    tool_obs = [o for o in mine if o.get("tools")]
    plain_obs = [o for o in mine if not o.get("tools")]

    return {
        "model": model,
        "observations": len(mine),
        "first_seen": mine[0].get("ts"),
        "last_seen": mine[-1].get("ts"),
        "last_ok": last_ok,
        "hours_since_ok": round(_age_hours(last_ok, now), 2) if last_ok else None,
        "uptime": uptime,
        "ok_pct_all": round(100 * len(ok_all) / len(mine)),
        "error_mix": dict(classes.most_common()),
        "latency_p50": _pct(lat, 50),
        "latency_p95": _pct(lat, 95),
        "ttft_p50": _pct(ttfts, 50),
        "tools_ok_pct": (round(100 * sum(1 for o in tool_obs if o["ok"]) / len(tool_obs))
                         if tool_obs else None),
        "tools_n": len(tool_obs),
        "plain_ok_pct": (round(100 * sum(1 for o in plain_obs if o["ok"]) / len(plain_obs))
                         if plain_obs else None),
        "plain_n": len(plain_obs),
        "verdict": verdict(mine, classes, now),
    }


def verdict(mine: list[dict], classes: Counter, now: datetime) -> str:
    """Terminal states first, then availability bands. Deliberately conservative:
    'gone' requires sustained evidence, because a single 404 is routinely a
    capacity flap and calling it death is how a live model gets struck off."""
    recent = [o for o in mine if _age_hours(o.get("ts", ""), now) <= 24]
    pool = recent or mine

    if any(o.get("class") == "eol_410" for o in pool):
        return "retired (410 end-of-life)"

    ok_n = sum(1 for o in pool if o["ok"])
    n = len(pool)
    if n < 3:
        return "insufficient data"

    ok_pct = 100 * ok_n / n
    if ok_n == 0:
        if classes.get("gone_404", 0) >= 3:
            return "gone (sustained 404)"
        if classes.get("rate_429", 0) >= 3:
            return "unreachable (rate-limited)"
        return "unreachable"
    if ok_pct >= 95:
        return "healthy"
    if ok_pct >= 60:
        return "flaky"
    return "capacity-limited"


def all_profiles(models: list[str] | None = None) -> list[dict]:
    obs = load()
    names = sorted({o.get("model") for o in obs if o.get("model")})
    if models:
        names = [m for m in names if m in set(models)]
    profs = [profile(m, obs) for m in names]
    order = {"healthy": 0, "flaky": 1, "capacity-limited": 2, "insufficient data": 3,
             "unreachable (rate-limited)": 4, "unreachable": 5,
             "gone (sustained 404)": 6, "retired (410 end-of-life)": 7}
    profs.sort(key=lambda p: (order.get(p["verdict"], 9), -(p.get("ok_pct_all") or 0)))
    return profs


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def build_report(models: list[str] | None = None) -> Path:
    """Roll the ledger into a committed profile table."""
    profs = all_profiles(models)
    obs_total = sum(p["observations"] for p in profs)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    L = [
        "# Model Behaviour Profiles",
        "",
        f"Rolled up {obs_total} observations across {len(profs)} models · generated {now}",
        "",
        "Every call made through `NemotronClient` is recorded, so these accumulate",
        "from ordinary use — assessments, delegations, one-off `nemo call`s — not",
        "from a dedicated probe run. Uptime columns are the share of calls that",
        "succeeded in that window; `n` is how many calls back that share.",
        "",
        "Verdicts distinguish **terminal** states (410 end-of-life, sustained 404)",
        "from **transient** ones (429 capacity, 5xx, timeout). A single 404 is not",
        "death — it is routinely a capacity flap — so `gone` needs sustained evidence.",
        "",
        "| Model | Verdict | 1h | 24h | 7d | All | Tools | p50 lat | p95 lat | Errors seen |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def cell(w):
        if not w or w["ok_pct"] is None:
            return "—"
        return f"{w['ok_pct']}% ({w['n']})"

    for p in profs:
        if p["observations"] == 0:
            continue
        tools = (f"{p['tools_ok_pct']}% ({p['tools_n']})"
                 if p.get("tools_ok_pct") is not None else "—")
        errs = ", ".join(f"{k}×{v}" for k, v in list(p["error_mix"].items())[:4]) or "—"
        L.append(
            f"| `{p['model']}` | {p['verdict']} | {cell(p['uptime']['1h'])} | "
            f"{cell(p['uptime']['24h'])} | {cell(p['uptime']['7d'])} | "
            f"{p['ok_pct_all']}% ({p['observations']}) | {tools} | "
            f"{p['latency_p50'] or '—'} | {p['latency_p95'] or '—'} | {errs} |"
        )

    flagged = [p for p in profs if p["verdict"].startswith(("retired", "gone", "unreachable"))]
    if flagged:
        L += ["", "## Do not route work here", ""]
        for p in flagged:
            last = f"last successful call {p['hours_since_ok']}h ago" if p["hours_since_ok"] else "never succeeded"
            L.append(f"- `{p['model']}` — **{p['verdict']}**, {last}")

    split = [p for p in profs
             if p.get("tools_ok_pct") is not None and p.get("plain_ok_pct") is not None
             and p["plain_ok_pct"] - p["tools_ok_pct"] >= 40]
    if split:
        L += ["", "## Answers plain chat but not tool calls", "",
              "Usable via `nemo call`, unusable as an agent backend.", ""]
        for p in split:
            L.append(f"- `{p['model']}` — plain {p['plain_ok_pct']}% "
                     f"({p['plain_n']}) vs tools {p['tools_ok_pct']}% ({p['tools_n']})")

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text("\n".join(L) + "\n", encoding="utf-8")
    PROFILE_JSON.write_text(json.dumps(profs, indent=2), encoding="utf-8")
    return PROFILE_PATH
