"""Idempotency keys and the dedup index (rules: docs/IDEMPOTENCY.md).

Keys are scoped to a queue. The index is rebuilt from the jobs after
recovery; each job records its canonical key.
"""

import unicodedata
from typing import Dict, Iterator, Optional, Tuple

from .errors import InvalidKey

MAX_KEY_CHARS = 200
_FORM = "NFKC"


def _compact(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def normalize_key(key) -> str:
    """The canonical form of an idempotency key (see module docstring)."""
    if not isinstance(key, str):
        raise InvalidKey("idempotency key must be a string")
    text = unicodedata.normalize(_FORM, key).strip()
    if not text:
        raise InvalidKey("idempotency key is empty")
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        raise InvalidKey("idempotency key contains control characters")
    if len(text) > MAX_KEY_CHARS:
        raise InvalidKey(f"idempotency key longer than {MAX_KEY_CHARS} characters")
    return _compact(text)


def scope(queue: str, normalized: str) -> str:
    """The index key for a normalised key on ``queue``."""
    return f"{queue}:{normalized}"


class _Entry:
    __slots__ = ("job_id", "expires_at")

    def __init__(self, job_id: str, expires_at: Optional[float]):
        self.job_id = job_id
        self.expires_at = expires_at   # None while the job is unfinished


class IdempotencyIndex:
    """Maps (queue, normalised key) to the job holding it."""

    def __init__(self):
        self._entries: Dict[str, _Entry] = {}
        self._by_job: Dict[str, str] = {}

    def lookup(self, queue: str, normalized: str, now: float) -> Optional[str]:
        """The job id holding the key, or None if the key is free at ``now``."""
        e = self._entries.get(scope(queue, normalized))
        if e is None:
            return None
        if e.expires_at is not None and now >= e.expires_at:
            return None
        return e.job_id

    def claim(self, queue: str, normalized: str, job_id: str) -> None:
        s = scope(queue, normalized)
        old = self._entries.get(s)
        if old is not None:
            self._by_job.pop(old.job_id, None)
        self._entries[s] = _Entry(job_id, None)
        self._by_job[job_id] = s

    def finished(self, job_id: str, expires_at: float) -> None:
        s = self._by_job.get(job_id)
        if s is not None:
            self._entries[s].expires_at = expires_at

    def reopened(self, job_id: str) -> None:
        """The job went back to waiting (operator retry): hold its key again."""
        s = self._by_job.get(job_id)
        if s is not None:
            self._entries[s].expires_at = None

    def drop(self, job_id: str) -> None:
        s = self._by_job.pop(job_id, None)
        if s is not None:
            e = self._entries.get(s)
            if e is not None and e.job_id == job_id:
                del self._entries[s]

    def prune(self, now: float) -> int:
        """Forget expired keys. Returns how many were forgotten."""
        dead = [s for s, e in self._entries.items() if e.expires_at is not None and now >= e.expires_at]
        for s in dead:
            e = self._entries.pop(s)
            self._by_job.pop(e.job_id, None)
        return len(dead)

    def key_of(self, job_id: str) -> Optional[str]:
        return self._by_job.get(job_id)

    def __len__(self) -> int:
        return len(self._entries)

    def items(self) -> Iterator[Tuple[str, str, Optional[float]]]:
        for s, e in sorted(self._entries.items()):
            yield s, e.job_id, e.expires_at

    def clear(self) -> None:
        self._entries.clear()
        self._by_job.clear()
