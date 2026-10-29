"""HTTP client for a local oMLX server's OpenAI-compatible chat completions endpoint.

Egress note: this client talks to a caller-configured host/port with no default
that reaches outside loopback unless the settings file says so. Callers are
responsible for the egress gate (see evals.harness.egress.classify) before ever
constructing a client around untrusted local content -- this module does not
enforce that gate itself, it only speaks HTTP.

Timing contract: oMLX's /v1/chat/completions response carries no timing block,
but evals.harness.runner._to_trial REQUIRES resp["timing"] to be a dict with a
positive numeric "total_s" (see runner.py) -- it raises otherwise. This client
satisfies that contract by injecting resp["timing"] itself, measuring
client-side wall-clock time around the whole HTTP request with time.monotonic().

Because requests are non-streaming, there is exactly one observable moment at
which any response content exists at all: when the full body arrives. There is
no way to observe time-to-first-token separately from total completion time
without switching to a streaming request. So ttft_s is set EQUAL to total_s.
This is a deliberate, documented choice, not an estimate and not a smaller
placeholder number -- reporting ttft_s == total_s is the honest statement of
what was actually measured for a non-streaming call.
"""
import json
import pathlib
import time
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SETTINGS_PATH = pathlib.Path.home() / ".omlx" / "settings.json"


def _load_settings(path: pathlib.Path) -> dict:
    """Best-effort settings load. Missing or malformed settings must never
    crash the caller -- they fall back to loopback defaults and no API key."""
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class OmlxClient:
    """Minimal client for oMLX's /v1/chat/completions endpoint.

    The API key is read from settings at call time, never cached in an
    attribute, never logged, and never passed as a command-line argument --
    it only ever travels inside the Authorization header of the HTTP request.
    """

    def __init__(self, settings_path: pathlib.Path = DEFAULT_SETTINGS_PATH,
                 timeout: float = 600.0):
        self._settings_path = pathlib.Path(settings_path)
        self._timeout = timeout

    def _settings(self) -> dict:
        return _load_settings(self._settings_path)

    def endpoint(self) -> str:
        s = self._settings()
        server = s.get("server")
        server = server if isinstance(server, dict) else {}
        host = server.get("host") or DEFAULT_HOST
        port = server.get("port") or DEFAULT_PORT
        return f"http://{host}:{port}/v1/chat/completions"

    def _api_key(self) -> str | None:
        s = self._settings()
        auth = s.get("auth")
        auth = auth if isinstance(auth, dict) else {}
        key = auth.get("api_key")
        return key if isinstance(key, str) and key else None

    def complete(self, model: str, messages: list[dict], max_tokens: int,
                 enable_thinking: bool) -> dict:
        """POST a chat completion. Returns the parsed JSON response with a
        client-measured resp["timing"] dict injected (see module docstring)."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if not enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        headers = {"Content-Type": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start = time.monotonic()
        resp = self._post(self.endpoint(), payload, headers)
        total_s = time.monotonic() - start

        resp["timing"] = {"ttft_s": total_s, "total_s": total_s}
        return resp

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        """The one network seam. Tests monkeypatch this method to avoid any
        live server dependency."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                body = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            raise RuntimeError(f"oMLX request failed: HTTP {e.code}: {body}") from None
        return json.loads(body)
