"""PriceServer: a fixed pool of worker threads serving price requests.

Requests are queued and handled first-come first-served by ``workers``
threads; ``submit`` returns a ``concurrent.futures.Future``. A handler that
raises sets the exception on the future (the worker keeps running).

Operations:
    quote      args: sku, region, qty=1, channel="web", options=None -> dict
    record     args: kind, name                                     -> value dict or None
    set_price  args: sku, base_cents, tiers=None                    -> new version
    set_region args: code, currency="USD", tax_bp=0, markup_bp=0, rounding="cent"
    set_fx     args: currency, rate
    set_promo  args: code, discount_bp, skus="*", active=True, min_qty=1
    stats      no args                                              -> stats_report()

Stats: ``server.requests`` (accepted), ``server.ok``, ``server.errors``,
``server.op.<op>`` per operation, and ``server.latency`` observations
(seconds, by the service clock) via Stats.observe.

With ``trace_reads=True`` the server installs a store read hook counting
``store.reads.<kind>`` so the dashboard can show which records are hot.
"""

import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Optional

from .service import PriceService

_STOP = object()


@dataclass
class Request:
    op: str
    args: dict = field(default_factory=dict)


class ServerClosed(RuntimeError):
    pass


class PriceServer:
    def __init__(self, service: PriceService, workers: int = 4, trace_reads: bool = False,
                 max_queue: int = 0):
        if workers < 1:
            raise ValueError("need at least one worker")
        self.service = service
        self.stats = service.stats
        self._queue: "queue.Queue" = queue.Queue(maxsize=max_queue)
        self._threads = []
        self._closed = False
        self._state_lock = threading.Lock()
        self._remove_hook = None
        if trace_reads:
            self._remove_hook = service.store.add_read_hook(self._trace_read)
        for i in range(workers):
            t = threading.Thread(target=self._run, name=f"price-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    # ------------------------------------------------------------ lifecycle

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self, wait: Optional[float] = 10.0) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        for _ in self._threads:
            self._queue.put(_STOP)
        for t in self._threads:
            t.join(wait)
        if self._remove_hook:
            self._remove_hook()

    # --------------------------------------------------------------- submit

    def submit(self, request: Request) -> Future:
        with self._state_lock:
            if self._closed:
                raise ServerClosed("server is closed")
        fut: Future = Future()
        self.stats.incr("server.requests")
        self._queue.put((request, fut, self.service.clock()))
        return fut

    def call(self, op: str, wait: Optional[float] = 30.0, **args):
        """Submit and wait up to ``wait`` seconds. Convenience for scripts and tests."""
        return self.submit(Request(op, args)).result(wait)

    # -------------------------------------------------------------- workers

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            request, fut, queued_at = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                result = self._dispatch(request)
            except BaseException as exc:  # noqa: BLE001 - reported via the future
                self.stats.incr("server.errors")
                fut.set_exception(exc)
            else:
                self.stats.incr("server.ok")
                fut.set_result(result)
            finally:
                self.stats.observe("server.latency", self.service.clock() - queued_at)

    def _dispatch(self, request: Request):
        op, a = request.op, dict(request.args)
        self.stats.incr(f"server.op.{op}")
        svc = self.service
        if op == "quote":
            return svc.quote(a["sku"], a["region"], a.get("qty", 1), a.get("channel", "web"),
                             a.get("options")).as_dict()
        if op == "record":
            rec = svc.record(a["kind"], a["name"])
            return None if rec is None or rec.deleted else rec.value
        if op == "set_price":
            return svc.set_price(a["sku"], a["base_cents"], a.get("tiers")).version
        if op == "set_region":
            return svc.set_region(**a).version
        if op == "set_fx":
            return svc.set_fx(a["currency"], a["rate"]).version
        if op == "set_promo":
            return svc.set_promo(**a).version
        if op == "stats":
            return svc.stats_report()
        raise ValueError(f"unknown op {op!r}")

    def _trace_read(self, key, record) -> None:
        kind = key[0] if isinstance(key, tuple) and key else "other"
        self.stats.incr(f"store.reads.{kind}")
