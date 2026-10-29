"""Outcome bookkeeping for the consult ledger: pure functions over ledger rows (no I/O).

Row types added on top of consult / FINDING / TRIGGER_OPPORTUNITY:
  OUTCOME  one per delivered consult: counts, escaped_later, downstream_tokens, no_findings
  ESCAPE   a bug found after the review that the review should have caught (append-only)

Old FINDING rows are never rewritten; `normalize_finding` reads both generations.
"""
from __future__ import annotations

import collections
import time

EXCLUDED_TRIGGERS = ("pilot",)      # a parallel experiment; kept out of every report and nag
VERIFIED_BY = ("requester", "independent_agent", "test", "human")
_METHOD_TO_VERIFIER = {"test": "test", "human_ruling": "human", "reproduced_counterexample": "test",
                       "source_inspection": "requester", "none": "none"}


def verifier_for(method: str | None) -> str:
    return _METHOD_TO_VERIFIER.get(method or "none", "requester")


def normalize_finding(r: dict) -> dict:
    """Legacy rows have `changed_action` (ambiguous) and no applied/verified_by; map them."""
    if "applied" in r:
        applied = str(r["applied"]).strip().lower() not in ("", "none", "no", "false")
    else:
        applied = r.get("disposition") == "applied"      # what 164 'changed_action: no' rows meant
    plan = r.get("changed_plan", r.get("changed_action", "no"))
    return {**r, "applied": applied, "changed_plan": plan,
            "verified_by": r.get("verified_by") or verifier_for(r.get("verification_method"))}


def attempt_status(c: dict) -> str:
    """delivered = a reply was captured intact; everything else is recorded-as-errored."""
    if c.get("sent") and not c.get("error") and (c.get("reply_chars") or 0) > 0:
        return "delivered"
    return "errored"


def _consults(rows):
    return [r for r in rows if r.get("started") and r.get("type") is None
            and r.get("trigger") not in EXCLUDED_TRIGGERS]


def _ts(s: str) -> float:
    return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) if s else 0.0


def pending_outcomes(rows: list[dict], hours: float = 24, now: str | None = None) -> list[dict]:
    done = {r.get("consult_id") for r in rows if r.get("type") == "OUTCOME"}
    t_now = _ts(now) if now else time.time()
    out = [c for c in _consults(rows)
           if attempt_status(c) == "delivered" and c["consult_id"] not in done
           and t_now - _ts(c["started"]) >= hours * 3600]
    return sorted(out, key=lambda c: c["started"])


def unrecorded(rows: list[dict], repo_id: str | None = None, hours: float = 24,
               now: str | None = None) -> list[dict]:
    """Delivered consults with neither a FINDING nor an OUTCOME row, optionally for one repo."""
    seen = {r.get("consult_id") for r in rows if r.get("type") in ("FINDING", "OUTCOME")}
    return [c for c in pending_outcomes(rows, hours, now)
            if c["consult_id"] not in seen and (repo_id is None or c.get("repo_id") == repo_id)]


def finding_command(cid: str) -> str:
    return (f"consult.py --record-finding {cid} --note '...'  then --record-outcome {cid}"
            f"  (or --record-outcome {cid} --no-findings)")


def record_gate(rows: list[dict], repo_id: str, limit: int = 5, now: str | None = None
                ) -> tuple[list[str], bool]:
    """(loud reminder lines, refuse?) for a new consult from this repo."""
    u = unrecorded(rows, repo_id, now=now)
    if not u:
        return [], False
    lines = [f"!! UNRECORDED CONSULTS: {len(u)} earlier consult(s) from THIS repo have no finding "
             f"or outcome, so the feedback loop is dead for them:"]
    lines += [f"   {c['consult_id']}: {finding_command(c['consult_id'])}" for c in u[:5]]
    if len(u) > 5:
        lines.append(f"   ... {len(u) - 5} more: consult.py --pending")
    return lines, len(u) >= limit


def record_command(cid: str) -> str:
    return (f"consult.py --record-outcome {cid} --outcome-note '...'   "
            f"(or add --no-findings if nothing actionable)")


def nag_lines(rows: list[dict], cap: int = 5, hours: float = 24, now: str | None = None) -> list[str]:
    p = pending_outcomes(rows, hours, now)
    if not p:
        return []
    lines = [f"OUTCOMES PENDING: {len(p)} delivered consult(s) older than {hours:g}h have no outcome "
             f"record (errored attempts are not counted):"]
    lines += [f"  {c['consult_id']}: {record_command(c['consult_id'])}" for c in p[:cap]]
    if len(p) > cap:
        lines.append(f"  ... {len(p) - cap} more; list all with consult.py --pending-outcomes")
    return lines


def findings_for(rows: list[dict], cid: str) -> list[dict]:
    return [normalize_finding(r) for r in rows
            if r.get("type") == "FINDING" and r.get("consult_id") == cid]


def derive_counts(rows: list[dict], cid: str) -> dict:
    fs = findings_for(rows, cid)
    return {"findings_total": len(fs),
            "findings_confirmed": sum(1 for f in fs if f.get("correctness") == "confirmed"),
            "false_positives": sum(1 for f in fs if f.get("correctness") == "disconfirmed"),
            "applied": sum(1 for f in fs if f["applied"])}


_COLS = ("delivered", "with_outcome", "confirmed", "false_positives", "applied", "escaped", "errored")


def stats(rows: list[dict]) -> dict:
    outcome = {}
    for r in rows:
        if r.get("type") == "OUTCOME":
            outcome[r.get("consult_id")] = r        # last one wins
    escapes = collections.Counter(r.get("consult_id") for r in rows if r.get("type") == "ESCAPE")
    res = {"by_kind": collections.defaultdict(lambda: dict.fromkeys(_COLS, 0)),
           "by_trigger": collections.defaultdict(lambda: dict.fromkeys(_COLS, 0))}
    for c in _consults(rows):
        cid = c["consult_id"]
        cells = (res["by_kind"][c.get("kind") or "other"], res["by_trigger"][c.get("trigger") or "other"])
        if attempt_status(c) != "delivered":
            for x in cells:
                x["errored"] += 1
            continue
        d = derive_counts(rows, cid)
        esc = (outcome.get(cid) or {}).get("escaped_later", 0) + escapes[cid]
        for x in cells:
            x["delivered"] += 1
            x["with_outcome"] += 1 if cid in outcome else 0
            x["confirmed"] += d["findings_confirmed"]
            x["false_positives"] += d["false_positives"]
            x["applied"] += d["applied"]
            x["escaped"] += esc
    return res


def format_stats(rows: list[dict]) -> str:
    s = stats(rows)
    head = ("delivered outcome confirmed false applied escaped errored")
    out = []
    for title, key in (("kind", "by_kind"), ("trigger", "by_trigger")):
        out.append(f"\nby {title}:   {head}")
        for k in sorted(s[key]):
            v = s[key][k]
            out.append(f"{k:28s}" + " ".join(f"{v[c]:>8d}" for c in _COLS))
    out.append(f"\n(experiment-tagged consults excluded; errored/unsent attempts are "
               f"counted, never nagged. 'confirmed' etc. sum FINDING rows; escaped sums OUTCOME "
               f"escaped_later plus ESCAPE rows.)")
    return "\n".join(out)
