"""HTTP client for a managed model gateway that speaks the Anthropic Messages API.

Such a gateway can front many vendors behind ONE wire format:
`{base}/v1/messages`, returning `usage.input_tokens`/`output_tokens`. So a single
client covers every model it serves, and callers need no per-vendor branching.

Normalization: `complete()` returns an OPENAI-SHAPED dict, not the raw
Anthropic response. That is deliberate -- `evals.harness.runner._to_trial` and
the CLI's scorer already speak the oMLX/OpenAI shape, so normalizing here means
zero changes downstream and one place where vendor shape is handled.

Egress: this client talks OFF-BOX. Callers MUST gate on
`evals.harness.egress.classify(...) == "sanctioned"` (or "local") before
sending anything derived from local files. This module speaks HTTP only and
does not enforce that gate.

Hostname: never hardcoded and never committed. It comes from the
ANTHROPIC_BASE_URL environment variable, falling back to the same key inside
the host CLI's user settings file (`env` block).

Credentials: minted by running the `apiKeyHelper` command string named in that
same settings file, via `sh -c` -- the identical mechanism the host CLI uses --
so there is no second copy of auth logic to drift. A non-zero exit from the
helper is rejected outright: whatever it printed is a diagnostic, not a token.
The token is held in memory only, cached until its TTL expires, never written to
disk, never logged, and never placed in a request payload or a command-line
argument.

Timing contract: like the oMLX client, this injects `resp["timing"]` with
client-measured wall clock, because `runner._to_trial` requires a positive
`total_s` and raises without it. Requests are non-streaming, so there is no
separately observable first-token moment: `ttft_s` is set EQUAL to `total_s`.
That is the honest statement of what was measured, not an estimate.
"""
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.request

DEFAULT_SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TTL_MS = 3_600_000

# How much of a gateway error body may be surfaced. See _post: the body is not
# ours, may echo the request (transcript text), and lands in logs.
_ERROR_BODY_CHARS = 200

# Patterns a gateway uses to name a model's real output-token ceiling when it
# rejects an oversized request. Deliberately few and explicit: an unmatched
# body yields no ceiling at all, because a guessed ceiling would silently
# re-measure a model at a budget nothing actually told us to use.
#
# The ceiling CANNOT be taken from discovery instead. A gateway's model-info
# endpoint can advertise a larger max_output_tokens than the backend enforces and
# then reject a request at the real limit -- so the advertised value would not
# have prevented the abort that motivated this. The rejection is the only
# trustworthy source.
_CEILING_PATTERNS = (
    re.compile(r"model limit of (\d+)"),
    re.compile(r"(?:lower|less) than (\d+)"),
)


# Delays between retries of a transient failure. Two retries, backing off, is
# enough for the transient gateway errors seen in practice (a 503 can cost a
# whole model in a sweep) without turning a genuinely dead
# gateway into a long stall across 19 models.
DEFAULT_RETRY_DELAYS = (2.0, 6.0)


class _Transient(Exception):
    """Internal marker: this failure is worth retrying. Never escapes _post."""


def _is_transient(status: int) -> bool:
    """Whether a status is worth retrying.

    5xx is the server saying it failed, not that the request was wrong. 429 is
    an explicit "later". Every other 4xx is a verdict on the request itself, and
    re-sending it just asks the same question again.
    """
    return status >= 500 or status == 429


class TokenCeilingError(RuntimeError):
    """A gateway rejection that named the model's real max_tokens ceiling.

    Subclasses RuntimeError so existing callers that catch RuntimeError keep
    working unchanged; `limit` is what lets complete() retry at a budget the
    model will actually accept.
    """

    def __init__(self, message: str, limit: int):
        super().__init__(message)
        self.limit = limit


def _parse_token_ceiling(body: str) -> int | None:
    """The ceiling a gateway error names, or None if it names none."""
    for pattern in _CEILING_PATTERNS:
        m = pattern.search(body or "")
        if m:
            return int(m.group(1))
    return None


# Anthropic stop_reason -> OpenAI finish_reason. An unrecognized reason passes
# through UNCHANGED rather than defaulting to "stop": mapping an unknown stop
# to "stop" would let a truncated or refused response be scored as clean.
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def _map_stop_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    return _STOP_REASON_MAP.get(reason, reason)


def _load_settings(path: pathlib.Path) -> dict:
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class SanctionedClient:
    """Client for the sanctioned gateway's Anthropic Messages endpoint."""

    def __init__(self, settings_path: pathlib.Path = DEFAULT_SETTINGS_PATH,
                 timeout: float = 900.0):
        self._settings_path = pathlib.Path(settings_path)
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        # model -> real output-token ceiling, learned from a rejection. Per
        # model, never global: one small model's ceiling must not silently
        # shrink every other model's budget.
        self._ceilings: dict[str, int] = {}
        self._retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS

    def ceiling_for(self, model: str) -> int | None:
        """The ceiling learned for this model, or None if none was ever hit."""
        return self._ceilings.get(model)

    def _settings(self) -> dict:
        return _load_settings(self._settings_path)

    def _env(self) -> dict:
        env = self._settings().get("env")
        return env if isinstance(env, dict) else {}

    def base_url(self) -> str:
        """Resolve the gateway base URL. Environment wins over settings so a
        caller can point at a different sanctioned host without editing files."""
        url = os.environ.get("ANTHROPIC_BASE_URL") or self._env().get("ANTHROPIC_BASE_URL")
        if not url:
            raise RuntimeError(
                "ANTHROPIC_BASE_URL is not set in the environment or in "
                f"{self._settings_path}'s env block; refusing to guess a gateway host"
            )
        return str(url).rstrip("/")

    def endpoint(self) -> str:
        return f"{self.base_url()}/v1/messages"

    def _ttl_seconds(self) -> float:
        raw = self._env().get("CLAUDE_CODE_API_KEY_HELPER_TTL_MS", DEFAULT_TTL_MS)
        try:
            return max(0.0, float(raw) / 1000.0)
        except (TypeError, ValueError):
            return DEFAULT_TTL_MS / 1000.0

    def _run_helper(self) -> str:
        """Mint a token by running the configured apiKeyHelper.

        `apiKeyHelper` is a shell COMMAND STRING, not a path -- the host CLI
        runs it as such, so a helper configured with arguments (or a pipeline)
        is legal. `sh -c <string>` is the faithful equivalent; `sh <string>`
        would treat the whole thing as a filename and fail on any helper that
        carries arguments.
        """
        helper = self._settings().get("apiKeyHelper")
        if not helper:
            raise RuntimeError(
                f"no apiKeyHelper configured in {self._settings_path}; "
                "cannot obtain a sanctioned-gateway token"
            )
        try:
            out = subprocess.run(["sh", "-c", str(helper)], capture_output=True,
                                 text=True, timeout=120)
        except Exception as e:
            raise RuntimeError(f"apiKeyHelper failed to run: {type(e).__name__}") from None
        # Check the exit status BEFORE looking at stdout. A failing helper often
        # prints a usage line or an error to stdout, and treating that as a
        # token would send it to the gateway as a Bearer credential. Only empty
        # stdout was rejected before, so a chatty failure got through.
        if out.returncode != 0:
            # Deliberately does NOT echo stdout or stderr: helper output can
            # contain credential material.
            raise RuntimeError(
                f"apiKeyHelper exited {out.returncode}; refusing to use its "
                "output as a token"
            )
        token = (out.stdout or "").strip()
        if not token:
            # Deliberately does NOT echo stderr: helper output can contain
            # credential material.
            raise RuntimeError("apiKeyHelper produced no token")
        return token

    def _auth_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token
        self._token = self._run_helper()
        self._token_expires_at = now + self._ttl_seconds()
        return self._token

    def complete(self, model: str, messages: list[dict], max_tokens: int,
                 enable_thinking: bool) -> dict:
        """POST a message and return an OpenAI-shaped response with injected
        timing. See the module docstring for why the shape is normalized."""
        headers = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "Authorization": f"Bearer {self._auth_token()}",
        }

        # Pre-clamp to a ceiling already learned for this model, so the
        # rejection costs one request per model rather than one per trial.
        budget = min(max_tokens, self._ceilings.get(model, max_tokens))

        start = time.monotonic()
        try:
            raw = self._post(self.endpoint(),
                             self._payload(model, messages, budget, enable_thinking),
                             headers)
        except TokenCeilingError as e:
            # Learn the real ceiling and retry ONCE. A second rejection at the
            # clamped budget propagates: retrying further would loop against a
            # gateway that is telling us something we cannot satisfy.
            self._ceilings[model] = e.limit
            raw = self._post(self.endpoint(),
                             self._payload(model, messages, min(budget, e.limit),
                                           enable_thinking),
                             headers)
        total_s = time.monotonic() - start

        out = self._normalize(raw)
        out["timing"] = {"ttft_s": total_s, "total_s": total_s}
        return out

    @staticmethod
    def _payload(model: str, messages: list[dict], max_tokens: int,
                 enable_thinking: bool) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Extended thinking is an Anthropic-only parameter; non-Claude models
        # behind a gateway may reject it. Budget must stay below max_tokens, and
        # max_tokens here is the EFFECTIVE budget -- deriving a thinking budget
        # from a size the model already rejected would just re-break the call.
        if enable_thinking and "claude" in model.lower() and max_tokens > 2048:
            payload["thinking"] = {"type": "enabled", "budget_tokens": max_tokens // 2}
        return payload

    @staticmethod
    def _normalize(raw: dict) -> dict:
        blocks = raw.get("content")
        blocks = blocks if isinstance(blocks, list) else []
        text = "".join(
            b.get("text") or ""
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        usage = raw.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return {
            "choices": [{
                "message": {"role": "assistant", "content": text},
                "finish_reason": _map_stop_reason(raw.get("stop_reason")),
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0) or 0,
                "completion_tokens": usage.get("output_tokens", 0) or 0,
                "prompt_tokens_details": {
                    "cached_tokens": usage.get("cache_read_input_tokens", 0) or 0
                },
            },
            "_raw_stop_reason": raw.get("stop_reason"),
        }

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        """The one network seam. Tests monkeypatch this to avoid live calls."""
        last: Exception | None = None
        # One initial attempt plus one per configured delay. A transient server
        # condition costs a retry; a deterministic client error costs nothing,
        # because _attempt re-raises those immediately.
        for i in range(len(self._retry_delays) + 1):
            try:
                return self._attempt(url, payload, headers)
            except _Transient as e:
                last = e.__cause__ or e
                if i < len(self._retry_delays):
                    time.sleep(self._retry_delays[i])
        raise RuntimeError(str(last)) from None

    def _attempt(self, url: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                body = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            # The error body is gateway-controlled and some gateways echo the
            # request back. The request here is transcript text, in a repo that
            # has a PRIVACY.md because of transcript text -- and this string
            # reaches the console and the run log. Truncate hard: the status
            # code plus a short prefix is enough to diagnose a gateway error.
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            snippet = body[:_ERROR_BODY_CHARS]
            if len(body) > _ERROR_BODY_CHARS:
                snippet += "... [truncated]"
            message = f"sanctioned gateway failed: HTTP {e.code}: {snippet}"
            # Parse the ceiling from the FULL body, but surface only the
            # truncated snippet: the limit may sit past the truncation point.
            limit = _parse_token_ceiling(body) if e.code == 400 else None
            if limit:
                raise TokenCeilingError(message, limit=limit) from None
            if _is_transient(e.code):
                raise _Transient(message) from RuntimeError(message)
            raise RuntimeError(message) from None
        except urllib.error.URLError as e:
            msg = f"sanctioned gateway unreachable: {e.reason}"
            # A refused or reset connection is the definition of transient.
            raise _Transient(msg) from RuntimeError(msg)
        return json.loads(body)
