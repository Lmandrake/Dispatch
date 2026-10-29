"""Webhook delivery for finished jobs.

:class:`WebhookDispatcher` is a :class:`taskmill.notify.Outbox` subscriber. For
each finished job it POSTs a JSON document to every configured endpoint::

    {"job_id": ..., "queue": ..., "kind": ..., "state": ..., "finished_at": ...,
     "attempts": ..., "result": ..., "last_error": ...}

The body is the canonical JSON encoding (see :mod:`taskmill.codec`) and is
signed with HMAC-SHA256 over the exact bytes sent; the hex digest travels in
``X-Taskmill-Signature: sha256=<hex>``. A receiver verifies it with
:func:`verify_signature`.

A delivery is attempted up to ``attempts`` times per endpoint. Between
attempts the dispatcher waits according to a :mod:`taskmill.backoff` policy
(``sleep`` is injectable). A response with status 200-299 is success; 4xx
other than 408 and 429 is permanent and not retried; anything else, and any
transport exception, is retried. When an endpoint ends up undelivered the
dispatcher raises :class:`DeliveryFailed`, so the outbox keeps the
notification for its own redelivery.

The transport is a callable ``(url, body, headers, timeout) -> status``; the
default uses :mod:`urllib.request`.
"""

import hashlib
import hmac
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import codec
from .backoff import parse_backoff
from .errors import TaskmillError
from .notify import Notification, Outbox

SIGNATURE_HEADER = "X-Taskmill-Signature"
DEFAULT_BACKOFF = {"kind": "exponential", "base": 0.5, "factor": 2.0, "max": 30.0}
PERMANENT_STATUSES = frozenset(range(400, 500)) - {408, 429}


class DeliveryFailed(TaskmillError):
    """At least one endpoint did not accept the webhook."""


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header: str) -> bool:
    return hmac.compare_digest(sign(secret, body), header or "")


def urllib_transport(url: str, body: bytes, headers: Dict[str, str], timeout: float) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


@dataclass
class EndpointStats:
    url: str
    delivered: int = 0
    failed: int = 0
    attempts: int = 0
    last_status: Optional[int] = None
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {"url": self.url, "delivered": self.delivered, "failed": self.failed,
                "attempts": self.attempts, "last_status": self.last_status, "last_error": self.last_error}


class WebhookDispatcher:
    def __init__(self, broker, secret: str, transport: Callable = urllib_transport,
                 attempts: int = 4, backoff: Optional[dict] = None, timeout: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep):
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.broker = broker
        self.secret = secret
        self.transport = transport
        self.attempts = attempts
        self.backoff = parse_backoff(backoff or DEFAULT_BACKOFF)
        self.timeout = timeout
        self.sleep = sleep
        self._lock = threading.Lock()
        self._endpoints: List[str] = []
        self._stats: Dict[str, EndpointStats] = {}

    def add_endpoint(self, url: str) -> None:
        with self._lock:
            if url not in self._stats:
                self._endpoints.append(url)
                self._stats[url] = EndpointStats(url)

    def attach(self, outbox: Outbox, name: str = "webhooks", queues=None, states=None) -> None:
        outbox.subscribe(name, self.deliver, queues=queues, states=states)

    def payload_for(self, note: Notification) -> dict:
        job = self.broker.get(note.job_id)
        return {"job_id": job.id, "queue": job.queue, "kind": job.kind, "state": job.state,
                "finished_at": job.finished_at, "attempts": job.attempts, "result": job.result,
                "last_error": job.last_error}

    def deliver(self, note: Notification) -> None:
        body = codec.encode(self.payload_for(note))
        headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(self.secret, body),
                   "X-Taskmill-Job": note.job_id}
        with self._lock:
            endpoints = list(self._endpoints)
        failed = [url for url in endpoints if not self._deliver_to(url, body, headers)]
        if failed:
            raise DeliveryFailed(f"{note.job_id}: not delivered to {', '.join(failed)}")

    def _deliver_to(self, url: str, body: bytes, headers: Dict[str, str]) -> bool:
        for attempt in range(1, self.attempts + 1):
            status, error = self._post(url, body, headers)
            self._record(url, status, error)
            if status is not None and 200 <= status < 300:
                self._finish(url, ok=True)
                return True
            if status in PERMANENT_STATUSES:
                break
            if attempt < self.attempts:
                self.sleep(self.backoff.delay(attempt, url))
        self._finish(url, ok=False)
        return False

    def _post(self, url: str, body: bytes, headers: Dict[str, str]):
        try:
            return self.transport(url, body, dict(headers), self.timeout), None
        except Exception as exc:  # noqa: BLE001 - any transport failure is retried
            return None, f"{type(exc).__name__}: {exc}"

    def _record(self, url: str, status: Optional[int], error: Optional[str]) -> None:
        with self._lock:
            st = self._stats[url]
            st.attempts += 1
            st.last_status = status
            st.last_error = error

    def _finish(self, url: str, ok: bool) -> None:
        with self._lock:
            st = self._stats[url]
            if ok:
                st.delivered += 1
            else:
                st.failed += 1

    def stats(self) -> Dict[str, dict]:
        with self._lock:
            return {url: self._stats[url].to_dict() for url in self._endpoints}
