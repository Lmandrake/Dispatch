"""Offline inspection of a data directory (``taskmill`` support tooling).

``describe(data_dir)`` summarises the snapshots and WAL segments on disk
without opening a broker (so it is safe to run next to a live one):
per-segment record counts and seq ranges, ops histogram, the newest
snapshot's position, and how many records recovery would replay.

``job_history(data_dir, job_id)`` lists every WAL record that mentions a job,
sorted by seq, which is the first thing to look at when a job "ran twice".
"""

import os
from collections import Counter
from typing import Dict, List

from . import snapshot as snapmod
from . import wal as walmod
from .errors import SnapshotError, WalCorrupt


def _wal_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "wal")


def _snap_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "snapshots")


def describe(data_dir: str) -> Dict:
    out: Dict = {"data_dir": data_dir, "snapshots": [], "segments": [], "ops": {}, "error": None}
    for path in snapmod.list_snapshots(_snap_dir(data_dir)):
        entry = {"file": os.path.basename(path)}
        try:
            snap = snapmod.read_snapshot(path)
            entry.update(last_seq=snap.last_seq, jobs=len(snap.jobs), ok=True)
        except SnapshotError as exc:
            entry.update(ok=False, error=str(exc))
        out["snapshots"].append(entry)
    try:
        res = walmod.scan(_wal_dir(data_dir))
    except WalCorrupt as exc:
        out["error"] = str(exc)
        return out
    for seg in res.segments:
        out["segments"].append({"file": os.path.basename(seg.path), "bytes": seg.size, "records": seg.records,
                                "min_seq": seg.min_seq, "max_seq": seg.max_seq})
    out["ops"] = dict(sorted(Counter(r["op"] for r in res.records).items()))
    newest = next((s for s in out["snapshots"] if s.get("ok")), None)
    base = newest["last_seq"] if newest else 0
    out["replay_records"] = sum(1 for r in res.records if r["seq"] > base)
    out["torn_tail"] = res.torn.to_dict() if res.torn else None
    return out


def _mentions(record: dict, job_id: str) -> bool:
    if record.get("id") == job_id:
        return True
    if record.get("op") == "enqueue" and record.get("job", {}).get("id") == job_id:
        return True
    if record.get("op") == "purge" and job_id in record.get("ids", ()):
        return True
    return False


def job_history(data_dir: str, job_id: str) -> List[dict]:
    res = walmod.scan(_wal_dir(data_dir))
    hits = [r for r in res.records if _mentions(r, job_id)]
    hits.sort(key=lambda r: r["seq"])
    out = []
    for r in hits:
        d = {"seq": r["seq"], "op": r["op"]}
        for k in ("at", "worker", "deadline", "run_at", "error", "to", "priority"):
            if k in r:
                d[k] = r[k]
        if "token" in r and r["token"]:
            d["token"] = r["token"][:6]
        out.append(d)
    return out


def render_history(rows: List[dict]) -> str:
    lines = []
    for r in rows:
        extra = " ".join(f"{k}={r[k]}" for k in ("worker", "token", "at", "deadline", "run_at", "to", "error",
                                                "priority") if k in r)
        lines.append(f"{r['seq']:>8}  {r['op']:<9} {extra}".rstrip())
    return "\n".join(lines) + ("\n" if lines else "")
