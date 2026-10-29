"""Job ids and lease tokens.

Job ids are ``<prefix>-<n>`` with ``n`` counting from 1 in enqueue order. The
counter is part of the broker state (snapshotted and replayed), so ids are
never reused across restarts. Lease tokens are random and opaque.
"""

import re
import secrets
import threading

_ID_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9_]*)-(?P<n>[1-9][0-9]*)$")


def format_job_id(prefix: str, n: int) -> str:
    return f"{prefix}-{n}"


def parse_job_id(job_id: str):
    """``(prefix, n)`` for a well-formed id, else ValueError."""
    m = _ID_RE.match(job_id or "")
    if not m:
        raise ValueError(f"malformed job id {job_id!r}")
    return m.group("prefix"), int(m.group("n"))


def job_id_sort_key(job_id: str):
    """Sort ids by their number (``job-2`` before ``job-10``); malformed ids last."""
    try:
        prefix, n = parse_job_id(job_id)
    except ValueError:
        return (1, "", 0, job_id)
    return (0, prefix, n, "")


def new_token() -> str:
    """A fresh, unguessable lease token."""
    return secrets.token_hex(12)


class Counter:
    """A thread-safe monotonic counter (used for worker ids and the like)."""

    def __init__(self, start: int = 0):
        self._n = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    @property
    def value(self) -> int:
        with self._lock:
            return self._n


_worker_ids = Counter()


def new_worker_id(prefix: str = "worker") -> str:
    return f"{prefix}-{_worker_ids.next()}"
