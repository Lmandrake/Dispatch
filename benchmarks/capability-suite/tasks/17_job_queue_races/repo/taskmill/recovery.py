"""Crash recovery: newest good snapshot plus the log records after it.

See docs/WAL.md for what recovery must reproduce. The returned
:class:`RecoveryReport` is shown by ``taskmill recover`` and kept on the
broker as ``broker.recovery``.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import snapshot as snapmod
from . import wal as walmod
from .state import ReplayError, State


@dataclass
class RecoveryReport:
    snapshot: Optional[str] = None
    snapshot_seq: int = 0
    skipped_snapshots: List[Tuple[str, str]] = field(default_factory=list)
    segments: int = 0
    records_seen: int = 0
    records_replayed: int = 0
    records_skipped: int = 0
    torn_tail: Optional[dict] = None
    last_seq: int = 0
    jobs: int = 0

    def to_dict(self) -> dict:
        return {
            "snapshot": os.path.basename(self.snapshot) if self.snapshot else None,
            "snapshot_seq": self.snapshot_seq,
            "skipped_snapshots": [[os.path.basename(p), why] for p, why in self.skipped_snapshots],
            "segments": self.segments,
            "records_seen": self.records_seen,
            "records_replayed": self.records_replayed,
            "records_skipped": self.records_skipped,
            "torn_tail": self.torn_tail,
            "last_seq": self.last_seq,
            "jobs": self.jobs,
        }

    def summary(self) -> str:
        src = f"snapshot {os.path.basename(self.snapshot)}" if self.snapshot else "no snapshot"
        line = (f"recovered {self.jobs} job(s) from {src} + {self.records_replayed} record(s) "
                f"({self.records_skipped} already in snapshot); last seq {self.last_seq}")
        if self.torn_tail:
            line += f"; discarded torn tail at byte {self.torn_tail['offset']} of {self.torn_tail['path']}"
        return line


def wal_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "wal")


def snapshot_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "snapshots")


def replay(state: State, records, after_seq: int) -> Tuple[int, int]:
    """Apply ``records`` newer than ``after_seq``. Returns (replayed, skipped)."""
    replayed = skipped = 0
    for rec in records:
        if rec["seq"] <= after_seq:
            skipped += 1
            continue
        try:
            state.apply(rec)
        except ReplayError as exc:
            raise ReplayError(f"seq {rec['seq']} ({rec.get('op')}): {exc}") from exc
        replayed += 1
    return replayed, skipped


def recover(state: State, data_dir: str, scan_result: walmod.ScanResult = None) -> RecoveryReport:
    report = RecoveryReport()
    snap, skipped = snapmod.load_latest(snapshot_dir(data_dir))
    report.skipped_snapshots = skipped
    if snap is not None:
        state.load(snap.jobs, snap.queues, snap.next_id, snap.last_seq)
        report.snapshot = snap.path
        report.snapshot_seq = snap.last_seq
    if scan_result is None:
        scan_result = walmod.scan(wal_dir(data_dir))
    report.segments = len(scan_result.segments)
    report.records_seen = len(scan_result.records)
    report.torn_tail = scan_result.torn.to_dict() if scan_result.torn else None
    report.records_replayed, report.records_skipped = replay(state, scan_result.records, report.snapshot_seq)
    report.last_seq = max(state.last_seq, scan_result.max_seq, report.snapshot_seq)
    state.last_seq = report.last_seq
    report.jobs = len(state.jobs)
    return report


def check(data_dir: str, config) -> dict:
    """Recover into a scratch state without touching the files (``taskmill recover --check``)."""
    state = State(config)
    report = recover(state, data_dir)
    out = report.to_dict()
    out["states"] = {}
    for job in state.jobs.values():
        out["states"][job.state] = out["states"].get(job.state, 0) + 1
    return out
