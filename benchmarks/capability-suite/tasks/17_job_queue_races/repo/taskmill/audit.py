"""Operator audit log.

Every operator action (cancel, retry, priority change, pause, resume, purge,
checkpoint) is appended to a JSON-lines file as one canonical JSON object::

    {"action": "cancel", "actor": "alice", "at": 1000000.0, "details": {}, "target": "job-1"}

The file is append-only and flushed after every entry. :class:`AuditedBroker`
wraps a broker, records the entry first (so an action that raises is still
visible, with ``details.error``) and then delegates. Everything the wrapper
does not override is forwarded to the wrapped broker unchanged.
"""

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from . import codec

ACTIONS = ("cancel", "retry", "set_priority", "pause", "resume", "purge", "checkpoint")


@dataclass(frozen=True)
class AuditEntry:
    at: float
    actor: str
    action: str
    target: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"at": self.at, "actor": self.actor, "action": self.action, "target": self.target,
                "details": self.details}

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEntry":
        return cls(d["at"], d["actor"], d["action"], d.get("target"), d.get("details") or {})


class AuditLog:
    def __init__(self, path: str, clock=None, max_bytes: Optional[int] = None, keep: int = 5):
        self.path = path
        self.clock = clock
        self.max_bytes = max_bytes
        self.keep = keep
        self._lock = threading.Lock()
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)

    def record(self, actor: str, action: str, target: Optional[str] = None,
               details: Optional[Dict[str, Any]] = None, at: Optional[float] = None) -> AuditEntry:
        when = at if at is not None else (self.clock() if self.clock is not None else 0.0)
        entry = AuditEntry(when, actor, action, target, codec.copy_json(details or {}))
        line = codec.encode(entry.to_dict()) + b"\n"
        with self._lock:
            self._rotate_if_needed(len(line))
            with open(self.path, "ab") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        return entry

    def _rotate_if_needed(self, incoming: int) -> None:
        if self.max_bytes is None or not os.path.exists(self.path):
            return
        if os.path.getsize(self.path) + incoming <= self.max_bytes:
            return
        oldest = f"{self.path}.{self.keep}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(self.keep - 1, 0, -1):
            src = f"{self.path}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{self.path}.{i + 1}")
        os.replace(self.path, f"{self.path}.1")

    def files(self) -> List[str]:
        """Existing log files, oldest first (rotated ones, then the live file)."""
        rotated = [f"{self.path}.{i}" for i in range(self.keep, 0, -1)]
        return [p for p in rotated + [self.path] if os.path.exists(p)]

    def entries(self) -> Iterator[AuditEntry]:
        for path in self.files():
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield AuditEntry.from_dict(codec.loads(line))

    def read(self, actor: Optional[str] = None, action: Optional[str] = None, target: Optional[str] = None,
             since: Optional[float] = None, until: Optional[float] = None) -> List[AuditEntry]:
        return [e for e in self.entries()
                if (actor is None or e.actor == actor)
                and (action is None or e.action == action)
                and (target is None or e.target == target)
                and (since is None or e.at >= since)
                and (until is None or e.at <= until)]

    def tail(self, n: int = 10) -> List[AuditEntry]:
        return list(self.entries())[-n:]

    def between(self, start: float, end: float, actor: Optional[str] = None) -> List[AuditEntry]:
        """Entries with ``start <= at < end``, optionally for one actor."""
        return [e for e in self.read(actor=actor, since=start) if e.at < end]

    def actors(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.entries():
            counts[e.actor] = counts.get(e.actor, 0) + 1
        return dict(sorted(counts.items()))

    def report(self, since: Optional[float] = None, until: Optional[float] = None) -> str:
        """A text summary: totals, per-action and per-actor counts, failures, and the time span."""
        entries = self.read(since=since, until=until)
        if not entries:
            return "audit: no entries\n"
        by_action: Dict[str, int] = {}
        by_actor: Dict[str, Dict[str, int]] = {}
        for e in entries:
            by_action[e.action] = by_action.get(e.action, 0) + 1
            by_actor.setdefault(e.actor, {})
            by_actor[e.actor][e.action] = by_actor[e.actor].get(e.action, 0) + 1
        failures = [e for e in entries if e.action.endswith(".failed")]
        lines = [f"audit: {len(entries)} entries from {min(e.at for e in entries):.0f} "
                 f"to {max(e.at for e in entries):.0f}, {len(failures)} failed"]
        lines += [f"  {a:<14} {n}" for a, n in sorted(by_action.items())]
        for actor, counts in sorted(by_actor.items()):
            lines.append(f"  {actor}: " + ", ".join(f"{a} x{n}" for a, n in sorted(counts.items())))
        return "\n".join(lines) + "\n"

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.entries():
            counts[e.action] = counts.get(e.action, 0) + 1
        return dict(sorted(counts.items()))


class AuditedBroker:
    """A broker whose operator actions are written to an :class:`AuditLog` first."""

    def __init__(self, broker, log: AuditLog, actor: str = "operator"):
        self._broker = broker
        self.log = log
        self.actor = actor
        if log.clock is None:
            log.clock = broker.clock

    def __getattr__(self, name: str):
        return getattr(self._broker, name)

    def as_actor(self, actor: str) -> "AuditedBroker":
        return AuditedBroker(self._broker, self.log, actor)

    def _audited(self, action: str, target: Optional[str], details: Dict[str, Any], fn, *args):
        self.log.record(self.actor, action, target, details)
        try:
            return fn(*args)
        except Exception as exc:
            self.log.record(self.actor, action + ".failed", target,
                            {**details, "error": f"{type(exc).__name__}: {exc}"})
            raise

    def cancel(self, job_id: str) -> bool:
        return self._audited("cancel", job_id, {}, self._broker.cancel, job_id)

    def retry(self, job_id: str) -> None:
        return self._audited("retry", job_id, {}, self._broker.retry, job_id)

    def set_priority(self, job_id: str, priority: int) -> None:
        return self._audited("set_priority", job_id, {"priority": priority},
                             self._broker.set_priority, job_id, priority)

    def pause(self, queue: str) -> None:
        return self._audited("pause", queue, {}, self._broker.pause, queue)

    def resume(self, queue: str) -> None:
        return self._audited("resume", queue, {}, self._broker.resume, queue)

    def purge(self) -> List[str]:
        ids = self._audited("purge", None, {}, self._broker.purge)
        self.log.record(self.actor, "purge.result", None, {"count": len(ids)})
        return ids

    def checkpoint(self) -> Optional[str]:
        return self._audited("checkpoint", None, {}, self._broker.checkpoint)
