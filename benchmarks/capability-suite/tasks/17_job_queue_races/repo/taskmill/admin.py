"""Admin API: a small JSON-over-HTTP interface for operators.

``AdminApp(broker)`` is a plain callable ``app(method, path, body) -> (status, dict)``
so it can be tested without sockets; ``serve(app, host, port)`` wraps it in
``http.server`` for real use. Routes:

    GET    /health                         {"ok": true, "closed": false}
    GET    /stats                          broker.stats()
    GET    /metrics                        {"metrics": broker.metrics.snapshot()}
    GET    /queues                         {"queues": [{"name", counts..., "paused"}]}
    GET    /queues/<q>                     one queue's counts
    GET    /queues/<q>/order               {"order": [job ids in reservation order]}
    POST   /queues/<q>/pause               {"paused": true}
    POST   /queues/<q>/resume              {"paused": false}
    POST   /queues/<q>/jobs                body: {"kind", "payload", "priority", "delay",
                                           "idempotency_key", "max_attempts", "tags"}
                                           -> 201 {"job_id", "created": true} or
                                              200 {"job_id", "created": false} (deduplicated)
    GET    /jobs?queue=&state=             {"jobs": [summaries]}
    GET    /jobs/<id>                      full job (lease token redacted)
    GET    /jobs/<id>/result               ResultView dict
    POST   /jobs/<id>/cancel               {"cancelled": bool}
    POST   /jobs/<id>/retry                {"state": "pending"}
    POST   /jobs/<id>/priority             body {"priority": n}
    GET    /leases                         {"leases": [...]} (tokens redacted)
    POST   /reap                           {"expired": [...]}
    POST   /purge                          {"purged": [...]}
    POST   /checkpoint                     {"snapshot": "<file name>" | null}
    GET    /trace?job_id=&limit=           {"events": [...]} (needs a Tracer)

Errors are ``{"error": "<message>", "type": "<ExceptionName>"}`` with the
status from the exception class (400 validation, 404 unknown, 409 conflict,
503 closed); an unknown route is 404, a known path with the wrong method 405.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .errors import TaskmillError, ValidationError
from .job import STATES

Route = Tuple[str, "re.Pattern", Callable]


def _redact(d: dict) -> dict:
    d = dict(d)
    if d.get("lease_token"):
        d["lease_token"] = d["lease_token"][:6] + "..."
    if d.get("token"):
        d["token"] = d["token"][:6] + "..."
    return d


class AdminApp:
    def __init__(self, broker, tracer=None):
        self.broker = broker
        self.tracer = tracer
        self._routes: List[Route] = []
        r = self._route
        r("GET", r"/health", self.health)
        r("GET", r"/stats", lambda q, b: (200, self.broker.stats()))
        r("GET", r"/metrics", lambda q, b: (200, {"metrics": self.broker.metrics.snapshot()}))
        r("GET", r"/queues", self.list_queues)
        r("GET", r"/queues/(?P<queue>[^/]+)", self.get_queue)
        r("GET", r"/queues/(?P<queue>[^/]+)/order", self.queue_order)
        r("POST", r"/queues/(?P<queue>[^/]+)/pause", self.pause)
        r("POST", r"/queues/(?P<queue>[^/]+)/resume", self.resume)
        r("POST", r"/queues/(?P<queue>[^/]+)/jobs", self.enqueue)
        r("GET", r"/jobs", self.list_jobs)
        r("GET", r"/jobs/(?P<job_id>[^/]+)", self.get_job)
        r("GET", r"/jobs/(?P<job_id>[^/]+)/result", self.get_result)
        r("POST", r"/jobs/(?P<job_id>[^/]+)/cancel", self.cancel)
        r("POST", r"/jobs/(?P<job_id>[^/]+)/retry", self.retry)
        r("POST", r"/jobs/(?P<job_id>[^/]+)/priority", self.priority)
        r("GET", r"/leases", lambda q, b: (200, {"leases": [_redact(l) for l in self.broker.leases()]}))
        r("POST", r"/reap", lambda q, b: (200, {"expired": self.broker.reap()}))
        r("POST", r"/purge", lambda q, b: (200, {"purged": self.broker.purge()}))
        r("POST", r"/checkpoint", self.checkpoint)
        r("GET", r"/trace", self.trace)

    def _route(self, method: str, pattern: str, fn: Callable) -> None:
        self._routes.append((method, re.compile("^" + pattern + "$"), fn))

    # ------------------------------------------------------------- dispatch

    def __call__(self, method: str, path: str, body: Optional[Any] = None) -> Tuple[int, Dict]:
        parts = urlsplit(path)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        matched_path = False
        for m, pattern, fn in self._routes:
            match = pattern.match(parts.path)
            if not match:
                continue
            matched_path = True
            if m != method:
                continue
            try:
                return fn(dict(query, **match.groupdict()), body if body is not None else {})
            except TaskmillError as exc:
                return exc.status, {"error": str(exc), "type": type(exc).__name__}
            except (TypeError, ValueError) as exc:
                return 400, {"error": str(exc), "type": type(exc).__name__}
        if matched_path:
            return 405, {"error": f"method {method} not allowed on {parts.path}", "type": "MethodNotAllowed"}
        return 404, {"error": f"no route for {parts.path}", "type": "NotFound"}

    # ---------------------------------------------------------------- views

    def health(self, q, body):
        return 200, {"ok": not self.broker.closed, "closed": self.broker.closed}

    def list_queues(self, q, body):
        out = []
        for name in self.broker.queue_names():
            d = {"name": name}
            d.update(self.broker.queue_stats(name))
            out.append(d)
        return 200, {"queues": out}

    def get_queue(self, q, body):
        d = {"name": q["queue"]}
        d.update(self.broker.queue_stats(q["queue"]))
        return 200, d

    def queue_order(self, q, body):
        return 200, {"order": self.broker.order(q["queue"])}

    def pause(self, q, body):
        self.broker.pause(q["queue"])
        return 200, {"paused": True}

    def resume(self, q, body):
        self.broker.resume(q["queue"])
        return 200, {"paused": False}

    def enqueue(self, q, body):
        if not isinstance(body, dict):
            raise ValidationError("body must be a JSON object")
        allowed = {"kind", "payload", "priority", "delay", "idempotency_key", "max_attempts", "tags"}
        extra = sorted(set(body) - allowed)
        if extra:
            raise ValidationError(f"unknown field(s): {', '.join(extra)}")
        if "kind" not in body:
            raise ValidationError("kind is required")
        res = self.broker.enqueue(q["queue"], body["kind"], body.get("payload"),
                                  priority=body.get("priority"), delay=body.get("delay"),
                                  idempotency_key=body.get("idempotency_key"),
                                  max_attempts=body.get("max_attempts"), tags=body.get("tags"))
        return (201 if res.created else 200), {"job_id": res.job_id, "created": res.created}

    def list_jobs(self, q, body):
        state = q.get("state")
        if state is not None and state not in STATES:
            raise ValidationError(f"unknown state {state!r}")
        jobs = self.broker.jobs(queue=q.get("queue"), state=state)
        return 200, {"jobs": [j.summary() for j in jobs]}

    def get_job(self, q, body):
        return 200, _redact(self.broker.get(q["job_id"]).to_dict())

    def get_result(self, q, body):
        return 200, self.broker.result(q["job_id"]).to_dict()

    def cancel(self, q, body):
        return 200, {"cancelled": self.broker.cancel(q["job_id"])}

    def retry(self, q, body):
        self.broker.retry(q["job_id"])
        return 200, {"state": "pending"}

    def priority(self, q, body):
        if not isinstance(body, dict) or "priority" not in body:
            raise ValidationError("body must be {\"priority\": n}")
        self.broker.set_priority(q["job_id"], body["priority"])
        return 200, {"priority": body["priority"]}

    def checkpoint(self, q, body):
        path = self.broker.checkpoint()
        return 200, {"snapshot": None if path is None else os.path.basename(path)}

    def trace(self, q, body):
        if self.tracer is None:
            return 404, {"error": "tracing is not enabled", "type": "NotFound"}
        limit = int(q["limit"]) if q.get("limit") else None
        return 200, {"events": self.tracer.events(job_id=q.get("job_id"), limit=limit)}


# ------------------------------------------------------------------ HTTP

def make_handler(app: AdminApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "taskmill-admin/1"

        def _send(self, status: int, doc: dict) -> None:
            data = (json.dumps(doc, sort_keys=True) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return "<invalid>"

        def do_GET(self):
            self._send(*app("GET", self.path))

        def do_POST(self):
            body = self._body()
            if body == "<invalid>":
                self._send(400, {"error": "body is not valid JSON", "type": "ValidationError"})
                return
            self._send(*app("POST", self.path, body))

        def log_message(self, fmt, *args):  # quiet by default
            pass

    return Handler


def serve(app: AdminApp, host: str = "127.0.0.1", port: int = 8470) -> ThreadingHTTPServer:
    """Start serving in the calling thread's caller's control: returns the server (call serve_forever)."""
    return ThreadingHTTPServer((host, port), make_handler(app))
