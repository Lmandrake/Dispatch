"""Snapshots: the broker's whole state at one log position.

A checkpoint writes ``snapshot-<last_seq>.json`` (12-digit, zero padded)
holding every job, the queue flags and the id counter as of ``last_seq``:
every change with ``seq <= last_seq`` is reflected in it, none after. The
file is written to a temporary name, fsynced and renamed into place, so a
snapshot is either complete or absent.

Format (``format`` 1)::

    {"format": 1, "last_seq": 41, "next_id": 17, "created_at": 1700000000.0,
     "queues": {"email": {"paused": false}},
     "jobs": [<Job.to_dict()>, ...],            # sorted by id number
     "checksum": "<sha256 hex of the canonical JSON of everything else>"}

The newest snapshot that loads cleanly wins; a damaged newest snapshot falls
back to the previous one (and recovery then needs more of the log).
"""

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import codec
from .errors import SnapshotError
from .ids import job_id_sort_key

SNAPSHOT_RE = re.compile(r"^snapshot-(\d{12})\.json$")
FORMAT = 1


def snapshot_name(last_seq: int) -> str:
    return f"snapshot-{last_seq:012d}.json"


@dataclass
class Snapshot:
    last_seq: int
    next_id: int
    jobs: List[dict] = field(default_factory=list)
    queues: Dict[str, dict] = field(default_factory=dict)
    created_at: float = 0.0
    path: Optional[str] = None

    def body(self) -> dict:
        return {
            "format": FORMAT,
            "last_seq": self.last_seq,
            "next_id": self.next_id,
            "created_at": self.created_at,
            "queues": self.queues,
            "jobs": sorted(self.jobs, key=lambda j: job_id_sort_key(j["id"])),
        }


def _checksum(body: dict) -> str:
    return hashlib.sha256(codec.encode(body)).hexdigest()


def write_snapshot(directory: str, snap: Snapshot) -> str:
    os.makedirs(directory, exist_ok=True)
    body = snap.body()
    doc = dict(body, checksum=_checksum(body))
    final = os.path.join(directory, snapshot_name(snap.last_seq))
    tmp = final + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(codec.encode(doc))
        fh.write(b"\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    snap.path = final
    return final


def read_snapshot(path: str) -> Snapshot:
    try:
        with open(path, "rb") as fh:
            doc = codec.loads(fh.read())
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"{os.path.basename(path)}: unreadable ({exc})") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise SnapshotError(f"{os.path.basename(path)}: unsupported snapshot format")
    checksum = doc.pop("checksum", None)
    if checksum != _checksum(doc):
        raise SnapshotError(f"{os.path.basename(path)}: checksum mismatch")
    return Snapshot(last_seq=doc["last_seq"], next_id=doc["next_id"], jobs=doc["jobs"],
                    queues=doc.get("queues", {}), created_at=doc.get("created_at", 0.0), path=path)


def list_snapshots(directory: str) -> List[str]:
    """Snapshot paths, newest (highest last_seq) first."""
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    found = []
    for name in names:
        m = SNAPSHOT_RE.match(name)
        if m:
            found.append((int(m.group(1)), os.path.join(directory, name)))
    found.sort(reverse=True)
    return [p for _, p in found]


def load_latest(directory: str):
    """``(snapshot or None, [skipped (path, error)])``."""
    skipped = []
    for path in list_snapshots(directory):
        try:
            return read_snapshot(path), skipped
        except SnapshotError as exc:
            skipped.append((path, str(exc)))
    return None, skipped


def prune_snapshots(directory: str, keep: int) -> List[str]:
    removed = []
    for path in list_snapshots(directory)[keep:]:
        try:
            os.remove(path)
            removed.append(os.path.basename(path))
        except FileNotFoundError:
            pass
    for name in os.listdir(directory) if os.path.isdir(directory) else ():
        if name.startswith("snapshot-") and name.endswith(".json.tmp"):
            os.remove(os.path.join(directory, name))
    return removed
