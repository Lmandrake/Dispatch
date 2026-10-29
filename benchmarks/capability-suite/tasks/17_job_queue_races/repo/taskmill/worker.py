"""WorkerPool: threads that reserve jobs, run handlers and ack/nack them.

Behaviour (prefetch, completion, heartbeats, shutdown) is described in
docs/WORKERS.md.
"""

import queue
import threading
import time
from typing import Dict, Iterable, List, Optional

from .errors import BrokerClosed, HandlerNotFound, LeaseLost, PermanentError, Retry
from .handlers import JobContext, Registry, default_registry
from .ids import new_worker_id


class WorkerPool:
    def __init__(self, broker, registry: Optional[Registry] = None, concurrency: int = 4,
                 queues: Optional[Iterable[str]] = None, poll: float = 0.1,
                 heartbeat_interval: Optional[float] = None, name: str = "worker", prefetch: int = 1):
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if prefetch < 1:
            raise ValueError("prefetch must be >= 1")
        self.broker = broker
        self.registry = registry or default_registry()
        self.concurrency = concurrency
        self.queues = None if queues is None else list(queues)
        self.poll = poll
        if heartbeat_interval is None:
            heartbeat_interval = max(0.05, broker.config.visibility_timeout / 3.0)
        self.heartbeat_interval = heartbeat_interval
        self.name = name
        self.prefetch = prefetch
        self._stop = threading.Event()
        self._closing = threading.Event()
        self._threads: List[threading.Thread] = []
        self._inflight: Dict[str, JobContext] = {}
        self._inflight_lock = threading.Lock()
        self._hb_thread: Optional[threading.Thread] = None
        self._completer: Optional[threading.Thread] = None
        self._done: "queue.Queue" = queue.Queue()
        self._started = False
        self.handled = 0
        self._handled_lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "WorkerPool":
        if self._started:
            return self
        self._started = True
        self._completer = threading.Thread(target=self._complete_loop, name=f"{self.name}-completer",
                                           daemon=True)
        self._completer.start()
        for _ in range(self.concurrency):
            wid = new_worker_id(self.name)
            t = threading.Thread(target=self._run, args=(wid,), name=wid, daemon=True)
            t.start()
            self._threads.append(t)
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, name=f"{self.name}-heartbeat",
                                           daemon=True)
        self._hb_thread.start()
        return self

    def stop(self, wait: Optional[float] = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(wait)
        self._closing.set()
        if self._completer is not None:
            self._completer.join(wait)
        if self._hb_thread is not None:
            self._hb_thread.join(wait)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def running(self) -> bool:
        return self._started and not self._stop.is_set()

    def inflight(self) -> List[str]:
        with self._inflight_lock:
            return sorted(ctx.job_id for ctx in self._inflight.values())

    # --------------------------------------------------------------- worker

    def _run(self, wid: str) -> None:
        buffered: List = []
        while not self._stop.is_set():
            while len(buffered) < self.prefetch and not self._stop.is_set():
                try:
                    res = self.broker.reserve(worker=wid, queues=self.queues,
                                              timeout=0 if buffered else self.poll)
                except BrokerClosed:
                    return
                if res is None:
                    break
                buffered.append(res)
                self._track(JobContext(self.broker, res, wid))
            if not buffered:
                continue
            res = buffered.pop(0)
            self._handle(wid, res)
        self._untrack(buffered)

    def _untrack(self, reservations) -> None:
        with self._inflight_lock:
            for res in reservations:
                self._inflight.pop(res.token, None)

    def _track(self, ctx: JobContext) -> None:
        with self._inflight_lock:
            self._inflight[ctx.token] = ctx

    def _handle(self, wid: str, res) -> None:
        with self._inflight_lock:
            ctx = self._inflight.get(res.token)
        if ctx is None:
            ctx = JobContext(self.broker, res, wid)
            self._track(ctx)
        started = time.monotonic()
        self.broker.hooks.fire("handler.start", job_id=res.job_id, worker=wid)
        try:
            fn = self.registry.get(res.kind)
        except HandlerNotFound as exc:
            self._submit(ctx, "no_handler", started, ("nack", str(exc), None, True))
            return
        try:
            result = fn(ctx)
        except PermanentError as exc:
            self._submit(ctx, "failed", started, ("nack", exc, None, True))
        except Retry as exc:
            self._submit(ctx, "retry", started, ("nack", exc.reason, exc.delay, False))
        except Exception as exc:  # noqa: BLE001 - a handler may raise anything
            self._submit(ctx, "retry", started, ("nack", exc, None, False))
        else:
            self._submit(ctx, "ok", started, ("ack", result))

    # ------------------------------------------------------------- completion

    def _submit(self, ctx: JobContext, outcome: str, started: float, action: tuple) -> None:
        item = (ctx, outcome, time.monotonic() - started, action)
        if self._started:
            self._done.put(item)
        else:
            self._complete(item)

    def _complete_loop(self) -> None:
        while True:
            try:
                item = self._done.get(timeout=self.poll)
            except queue.Empty:
                if self._closing.is_set():
                    return
                continue
            self._complete(item)

    def _complete(self, item) -> None:
        ctx, outcome, elapsed, action = item
        res = ctx.reservation
        try:
            if action[0] == "ack":
                try:
                    self.broker.ack(res.token, action[1])
                except (LeaseLost, BrokerClosed):
                    outcome = "lost"
                except Exception as exc:  # e.g. ResultTooLarge
                    outcome = "failed"
                    if not self._nack(ctx, exc, None, True):
                        outcome = "lost"
            else:
                _, error, retry_in, permanent = action
                if not self._nack(ctx, error, retry_in, permanent) or ctx.lost:
                    outcome = "lost"
        finally:
            with self._inflight_lock:
                self._inflight.pop(res.token, None)
            self.broker.metrics.inc("worker.handled", kind=res.kind, outcome=outcome)
            self.broker.metrics.observe("worker.run_seconds", elapsed)
            with self._handled_lock:
                self.handled += 1
            self.broker.hooks.fire("handler.end", job_id=res.job_id, worker=ctx.worker, ok=outcome == "ok")

    def _nack(self, ctx: JobContext, error, retry_in, permanent) -> bool:
        try:
            self.broker.nack(ctx.token, error, retry_in=retry_in, permanent=permanent)
            return True
        except (LeaseLost, BrokerClosed):
            return False

    # ------------------------------------------------------------ heartbeat

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval):
            self.heartbeat_now()

    def heartbeat_now(self) -> int:
        """Renew every in-flight lease once. Returns how many renewals succeeded."""
        with self._inflight_lock:
            contexts = list(self._inflight.values())
        ok = 0
        for ctx in contexts:
            if ctx.lost:
                continue
            try:
                self.broker.heartbeat(ctx.token)
                ok += 1
            except LeaseLost as exc:
                ctx.mark_lost(str(exc))
            except BrokerClosed:
                return ok
        return ok

    # -------------------------------------------------------------- helpers

    def drain(self, timeout: float = 10.0, queues: Optional[Iterable[str]] = None) -> bool:
        """Wait until no job is pending/reserved (delayed ones excluded) or timeout."""
        names = None if queues is None else set(queues)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            busy = False
            for job in self.broker.jobs():
                if names is not None and job.queue not in names:
                    continue
                if job.state in ("pending", "reserved"):
                    busy = True
                    break
            if not busy and not self.inflight():
                return True
            time.sleep(0.01)
        return False


def run_one(broker, registry: Optional[Registry] = None, worker: str = "inline",
            queues: Optional[Iterable[str]] = None) -> Optional[str]:
    """Reserve and handle one job in the calling thread. Returns its id, or None."""
    pool = WorkerPool(broker, registry, concurrency=1, queues=queues)
    res = broker.reserve(worker=worker, queues=pool.queues)
    if res is None:
        return None
    pool._handle(worker, res)
    return res.job_id
