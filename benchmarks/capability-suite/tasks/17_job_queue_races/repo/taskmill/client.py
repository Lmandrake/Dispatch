"""A small client for the admin API (``taskmill serve``).

    c = AdminClient("http://127.0.0.1:8470")
    job_id = c.enqueue("email", "send", {"to": "a@example.org"}, idempotency_key="order-17")
    c.result(job_id)

Every method returns the decoded JSON document. A non-2xx response raises
:class:`AdminError` carrying the status and the server's error message.

``AdminClient.local(app)`` builds a client that calls an :class:`AdminApp`
directly (no sockets), which is how the CLI and the tests use it.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode


class AdminError(Exception):
    def __init__(self, status: int, message: str, kind: str = ""):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message
        self.kind = kind


class AdminClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8470", timeout: float = 10.0,
                 transport: Optional[Callable] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or self._http

    @classmethod
    def local(cls, app) -> "AdminClient":
        return cls("local:", transport=lambda method, path, body: app(method, path, body))

    # ------------------------------------------------------------ transport

    def _http(self, method: str, path: str, body: Optional[Any]):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                doc = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                doc = {"error": exc.reason}
            return exc.code, doc

    def _call(self, method: str, path: str, body: Optional[Any] = None) -> Dict:
        status, doc = self._transport(method, path, body)
        if not 200 <= status < 300:
            raise AdminError(status, doc.get("error", "request failed"), doc.get("type", ""))
        return doc

    @staticmethod
    def _q(**params) -> str:
        params = {k: v for k, v in params.items() if v is not None}
        return ("?" + urlencode(params)) if params else ""

    # ------------------------------------------------------------- methods

    def health(self) -> Dict:
        return self._call("GET", "/health")

    def stats(self) -> Dict:
        return self._call("GET", "/stats")

    def metrics(self) -> Dict[str, float]:
        return self._call("GET", "/metrics")["metrics"]

    def queues(self) -> List[Dict]:
        return self._call("GET", "/queues")["queues"]

    def queue(self, name: str) -> Dict:
        return self._call("GET", f"/queues/{quote(name)}")

    def order(self, name: str) -> List[str]:
        return self._call("GET", f"/queues/{quote(name)}/order")["order"]

    def pause(self, name: str) -> None:
        self._call("POST", f"/queues/{quote(name)}/pause")

    def resume(self, name: str) -> None:
        self._call("POST", f"/queues/{quote(name)}/resume")

    def enqueue(self, queue: str, kind: str, payload: Any = None, **options) -> str:
        body = dict(options, kind=kind, payload=payload)
        return self._call("POST", f"/queues/{quote(queue)}/jobs", body)["job_id"]

    def jobs(self, queue: Optional[str] = None, state: Optional[str] = None) -> List[Dict]:
        return self._call("GET", "/jobs" + self._q(queue=queue, state=state))["jobs"]

    def job(self, job_id: str) -> Dict:
        return self._call("GET", f"/jobs/{quote(job_id)}")

    def result(self, job_id: str) -> Dict:
        return self._call("GET", f"/jobs/{quote(job_id)}/result")

    def cancel(self, job_id: str) -> bool:
        return self._call("POST", f"/jobs/{quote(job_id)}/cancel")["cancelled"]

    def retry(self, job_id: str) -> None:
        self._call("POST", f"/jobs/{quote(job_id)}/retry")

    def set_priority(self, job_id: str, priority: int) -> None:
        self._call("POST", f"/jobs/{quote(job_id)}/priority", {"priority": priority})

    def leases(self) -> List[Dict]:
        return self._call("GET", "/leases")["leases"]

    def reap(self) -> List[str]:
        return self._call("POST", "/reap")["expired"]

    def purge(self) -> List[str]:
        return self._call("POST", "/purge")["purged"]

    def checkpoint(self) -> Optional[str]:
        return self._call("POST", "/checkpoint")["snapshot"]

    def trace(self, job_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        return self._call("GET", "/trace" + self._q(job_id=job_id, limit=limit))["events"]
