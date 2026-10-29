"""Thin client for TypeSafe's System One endpoint.

Stdlib only, deliberately. The API is a single POST, so a dependency buys nothing here
and costs an install step on machines where that is awkward. TypeSafe does publish an
official SDK (`pip install typesafe-sdk`) whose retry policy is richer than this one;
prefer it if this file starts growing.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
CREDENTIALS = pathlib.Path.home() / ".config" / "consultjev" / "env"
#: When this package lives inside Dispatch (providers/jev), the private overlay may name a
#: different key file (`overlay.json` -> "credentials_file"). Standalone, the default holds.
_DISPATCH = pathlib.Path(__file__).resolve().parents[3]


def credentials_path() -> pathlib.Path:
    """The key file: the Dispatch overlay's `credentials_file` if one is set, else the default."""
    if (_DISPATCH / "dispatchlib" / "providers.py").is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_dispatch_providers", _DISPATCH / "dispatchlib" / "providers.py")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            named = mod.overlay_config("jev").get("credentials_file")
        except Exception:  # an unreadable overlay is "not configured", never a crash
            named = None
        if named:
            return pathlib.Path(os.path.expanduser(str(named)))
    return CREDENTIALS

# 429 and 529 are the two statuses TypeSafe documents as worth retrying. Anything else
# is a request we got wrong, and retrying a 422 just spends time to be told so again.
RETRYABLE = (429, 529)

# TypeSafe's published price, 2026-09-28: input only, output free, because the answer is a
# typed value rather than generated text. Re-check before quoting it; it is their number.
USD_PER_MILLION_INPUT_TOKENS = 0.042

# Measured on the CoverageMap battery: ~940 input tokens for a risk statement, a passage of
# a few hundred words, and four questions. Used only for pre-flight estimates.
TYPICAL_INPUT_TOKENS = 940


def estimate_cost_usd(calls: int, tokens_per_call: int = TYPICAL_INPUT_TOKENS) -> float:
    """What a run of this size will cost, before making any of the calls.

    Deliberately an over-estimate rather than an average: a budget guard that trips late is
    not a guard. Callers should refuse to run rather than warn.
    """
    return calls * tokens_per_call / 1_000_000 * USD_PER_MILLION_INPUT_TOKENS


class JevError(RuntimeError):
    """A call failed in a way retrying will not fix."""


def load_api_key() -> str:
    """The key from the environment, falling back to the file outside this repo.

    Raises rather than returning None: a missing key produces a 401 several frames
    later, and the remedy is not obvious from there.
    """
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key
    creds = credentials_path()
    if creds.exists():
        for line in creds.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip()
    raise JevError(
        f"Jev is not configured: no TYPESAFE_API_KEY in the environment and none found in {creds}. "
        "Create a key at https://console.typesafe.ai/keys"
    )


@dataclass
class Answer:
    """One typed answer. Exactly one of noul / choice / score is populated.

    `confidence` is None for a noul, because TypeSafe only derives confidence from a
    probability distribution and a noul does not return one. None here means "the API
    reports no confidence for this question type", never "confidence was zero".
    """

    question_id: str
    type: str
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    legend: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, question_id: str, raw: dict) -> "Answer":
        return cls(
            question_id=question_id,
            type=raw["type"],
            noul=raw.get("noul"),
            choice=raw.get("choice"),
            score=raw.get("score"),
            confidence=raw.get("confidence"),
            probabilities=raw.get("probabilities") or {},
            legend=raw.get("legend") or {},
        )


@dataclass
class Response:
    model: str
    answers: dict[str, Answer]
    input_tokens: int
    output_tokens: int
    elapsed_ms: int

    def __getitem__(self, question_id: str) -> Answer:
        return self.answers[question_id]


def ask(
    state,
    questions: dict[str, dict],
    *,
    model: str = "jev-latest",
    api_key: str | None = None,
    timeout: float = 120.0,
    max_attempts: int = 4,
) -> Response:
    """Evaluate one state against a map of typed questions.

    Every question is evaluated independently and in parallel against the same state,
    so asking twelve costs little more latency than asking one. Batch generously.
    """
    key = api_key or load_api_key()
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )

    started = time.perf_counter()
    last_status = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as raw:
                payload = json.loads(raw.read())
            break
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            if exc.code not in RETRYABLE or attempt == max_attempts - 1:
                detail = exc.read()[:600].decode("utf-8", "replace")
                raise JevError(f"HTTP {exc.code} from TypeSafe: {detail}") from exc
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # A transient network blip (DNS, reset, timeout) is retryable, and must raise
            # JevError when it is not. An unhandled URLError once escaped a worker pool and
            # killed a whole run, discarding every answer already paid for.
            last_status = f"network: {exc}"
            if attempt == max_attempts - 1:
                raise JevError(f"Network failure after {max_attempts} attempts: {exc}") from exc
            time.sleep(2**attempt)
    else:  # pragma: no cover - loop always breaks or raises
        raise JevError(f"Gave up after {max_attempts} attempts, last status {last_status}")

    usage = payload.get("usage") or {}
    return Response(
        model=payload["model"],
        answers={
            qid: Answer.from_api(qid, raw) for qid, raw in payload["answers"].items()
        },
        input_tokens=usage.get("input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
