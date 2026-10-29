"""Per-queue ordering: a ready heap and a delay heap (rules: docs/ORDERING.md).

``ready`` holds pending jobs keyed ``(priority, ready_at, seq)``; ``delayed``
holds delayed jobs keyed ``(run_at, seq)``. Removal is lazy: the heaps hold
``(key..., job_id)`` entries plus a live map, and entries whose job is no
longer live (or was pushed again with a new key) are skipped at the top.
"""

import heapq
from typing import Dict, Iterator, List, Optional, Tuple

from .job import DELAYED, PENDING, Job


class JobQueue:
    def __init__(self, name: str):
        self.name = name
        self._ready: List[Tuple] = []
        self._delayed: List[Tuple] = []
        # job_id -> the entry currently considered live for that job
        self._live: Dict[str, Tuple] = {}
        self._jobs: Dict[str, Job] = {}

    # --------------------------------------------------------------- helpers

    @staticmethod
    def ready_key(job: Job) -> Tuple:
        return ("r", job.priority, job.ready_at, job.seq, job.id)

    @staticmethod
    def delay_key(job: Job) -> Tuple:
        return ("d", job.run_at, job.seq, job.id)

    def _is_live(self, entry: Tuple) -> bool:
        return self._live.get(entry[-1]) is entry

    def _clean_top(self, heap: List[Tuple]) -> None:
        while heap and not self._is_live(heap[0]):
            heapq.heappop(heap)

    # ------------------------------------------------------------------ API

    def push(self, job: Job) -> None:
        """Add (or re-add) ``job`` according to its state (pending or delayed)."""
        if job.state == PENDING:
            entry = self.ready_key(job)
            heapq.heappush(self._ready, entry)
        elif job.state == DELAYED:
            entry = self.delay_key(job)
            heapq.heappush(self._delayed, entry)
        else:
            raise ValueError(f"cannot queue {job.id} in state {job.state}")
        self._live[job.id] = entry
        self._jobs[job.id] = job

    def discard(self, job_id: str) -> bool:
        """Forget ``job_id`` (its heap entries become dead). True if it was queued."""
        self._jobs.pop(job_id, None)
        return self._live.pop(job_id, None) is not None

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._live

    def promote_due(self, now: float) -> List[Job]:
        """Move every delayed job whose run_at has passed to the ready heap."""
        promoted = []
        while True:
            self._clean_top(self._delayed)
            if not self._delayed or self._delayed[0][1] > now:
                break
            entry = heapq.heappop(self._delayed)
            job = self._jobs[entry[-1]]
            job.state = PENDING
            job.ready_at = now
            self.push(job)
            promoted.append(job)
        return promoted

    def peek(self, now: float) -> Optional[Job]:
        """The job ``pop`` would return, without removing it."""
        self._clean_top(self._ready)
        if not self._ready:
            self.promote_due(now)
            self._clean_top(self._ready)
        if not self._ready:
            return None
        return self._jobs[self._ready[0][-1]]

    def pop(self, now: float) -> Optional[Job]:
        job = self.peek(now)
        if job is not None:
            self.discard(job.id)
        return job

    def next_run_at(self) -> Optional[float]:
        """Earliest run_at among delayed jobs (for wait timeouts), or None."""
        self._clean_top(self._delayed)
        return self._delayed[0][1] if self._delayed else None

    # -------------------------------------------------------------- counting

    def count_ready(self) -> int:
        return sum(1 for e in self._live.values() if e[0] == "r")

    def count_delayed(self) -> int:
        return sum(1 for e in self._live.values() if e[0] == "d")

    def __len__(self) -> int:
        return len(self._live)

    def job_ids(self) -> Iterator[str]:
        return iter(list(self._live))

    def ordered(self, now: float) -> List[Job]:
        """Every queued job in the order it would be reserved (ready first, then by run_at)."""
        self.promote_due(now)
        ready = sorted(e for e in self._live.values() if e[0] == "r")
        delayed = sorted(e for e in self._live.values() if e[0] == "d")
        return [self._jobs[e[-1]] for e in ready + delayed]

    def compact(self) -> int:
        """Drop dead heap entries; returns how many were dropped."""
        before = len(self._ready) + len(self._delayed)
        self._ready = [e for e in self._ready if self._is_live(e)]
        self._delayed = [e for e in self._delayed if self._is_live(e)]
        heapq.heapify(self._ready)
        heapq.heapify(self._delayed)
        return before - len(self._ready) - len(self._delayed)

    def __repr__(self) -> str:
        return f"JobQueue({self.name!r}, ready={self.count_ready()}, delayed={self.count_delayed()})"


def best_of(queues, now: float) -> Optional[Tuple[JobQueue, Job]]:
    """Across several queues, the queue and job that should be reserved next.

    Jobs compare by ``(priority, ready_at, seq)`` as within one queue.
    """
    best = None
    for q in queues:
        job = q.peek(now)
        if job is None:
            continue
        key = (job.priority, job.ready_at, job.seq)
        if best is None or key < best[0]:
            best = (key, q, job)
    return None if best is None else (best[1], best[2])
