"""Accessor: a thin wrapper over the OpenAI SDK pointed at NVIDIA NIM.

Adds only what the bare SDK lacks for this project: env-based key loading, a
polite client-side rate limiter (free tier is ~40 RPM), transient-error
retries, vision message helpers, and streaming timing capture (TTFT + decode
tokens/sec) used by the assessment harness.
"""

from __future__ import annotations

import base64
import mimetypes
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx
from openai import OpenAI
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from . import config, telemetry


class RateLimiter:
    """Thread-safe minimum-interval limiter (approximate RPM cap)."""

    def __init__(self, rpm: int = config.DEFAULT_RPM):
        self.min_interval = 60.0 / max(rpm, 1)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval


@dataclass
class ChatResult:
    text: str
    model: str
    ok: bool = True
    error: str | None = None
    # Timing (seconds).
    ttft: float | None = None          # time to first token (streamed)
    latency: float = 0.0               # total wall time
    # Token accounting (from usage when available).
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tokens_per_sec: float | None = None
    # Reasoning models emit hidden reasoning before the answer.
    reasoning_chars: int = 0
    had_reasoning: bool = False
    # Function/tool calling. Populated on the non-streaming path, which is what
    # the agentic harness uses: NIM's streamed tool_call deltas arrive
    # fragmented and inconsistently across models, and correctness — not TTFT —
    # is what a tool loop is measuring.
    tool_calls: list = field(default_factory=list)
    finish_reason: str | None = None
    raw: Any = field(default=None, repr=False)


@dataclass
class ImageResult:
    model: str
    ok: bool = True
    latency: float = 0.0
    image: bytes | None = field(default=None, repr=False)
    width: int | None = None
    height: int | None = None
    error: str | None = None


# Errors worth retrying (rate limits, transient upstream failures).
try:  # openai>=1.0 exception classes
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    _RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
except Exception:  # pragma: no cover - defensive
    _RETRYABLE = (Exception,)


def _is_retryable(exc: BaseException) -> bool:
    """Retry the usual transient errors, plus NIM's 'temporarily overloaded'
    (503-class) which arrives as a generic status error for busy big models."""
    if isinstance(exc, _RETRYABLE):
        return True
    msg = str(exc).lower()
    return "overloaded" in msg or "temporarily" in msg or "503" in msg


class NemotronClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = config.BASE_URL,
        rpm: int = config.DEFAULT_RPM,
        timeout: float = 180.0,
    ):
        self.api_key = api_key or config.get_api_key()
        self.base_url = base_url
        self.limiter = RateLimiter(rpm)
        self._client = OpenAI(api_key=self.api_key, base_url=base_url, timeout=timeout)

    # ---- discovery -------------------------------------------------------

    def list_models(self) -> list[str]:
        self.limiter.wait()
        return sorted(m.id for m in self._client.models.list().data)

    # ---- chat ------------------------------------------------------------

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        stop=stop_after_attempt(2),
        reraise=True,
    )
    def _create(self, **kwargs):
        self.limiter.wait()
        return self._client.chat.completions.create(**kwargs)

    def chat(
        self,
        model: str,
        messages: Sequence[dict],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = True,
        **extra: Any,
    ) -> ChatResult:
        """One chat turn, recorded to the behaviour ledger.

        Instrumenting here rather than at each call site means every path in the
        codebase — battery, agentic loop, judge, `nemo call`, the delegation
        skill — contributes availability and latency evidence for free.
        """
        r = self._chat_uninstrumented(
            model, messages, max_tokens, temperature, stream, **extra
        )
        telemetry.record(
            model, r.ok, r.error, r.latency, r.ttft, r.completion_tokens,
            kind="chat", tools=bool(extra.get("tools")),
        )
        return r

    def _chat_uninstrumented(
        self,
        model: str,
        messages: Sequence[dict],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = True,
        **extra: Any,
    ) -> ChatResult:
        """One chat turn. Streams by default to capture TTFT + decode rate."""
        start = time.monotonic()
        try:
            if stream:
                return self._chat_streaming(
                    model, messages, max_tokens, temperature, start, **extra
                )
            resp = self._create(
                model=model,
                messages=list(messages),
                max_tokens=max_tokens,
                temperature=temperature,
                **extra,
            )
            latency = time.monotonic() - start
            usage = getattr(resp, "usage", None)
            ct = getattr(usage, "completion_tokens", None)
            choice = resp.choices[0]
            return ChatResult(
                text=choice.message.content or "",
                model=model,
                latency=latency,
                tool_calls=_tool_calls_as_dicts(choice.message),
                finish_reason=getattr(choice, "finish_reason", None),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=ct,
                tokens_per_sec=(ct / latency if ct and latency else None),
                raw=resp,
            )
        except Exception as exc:  # surface, don't crash a batch run
            return ChatResult(
                text="",
                model=model,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                latency=time.monotonic() - start,
            )

    def _chat_streaming(
        self, model, messages, max_tokens, temperature, start, **extra
    ) -> ChatResult:
        stream = self._create(
            model=model,
            messages=list(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
            **extra,
        )
        chunks: list[str] = []
        reasoning: list[str] = []
        ttft: float | None = None
        usage = None
        for event in stream:
            if getattr(event, "usage", None):
                usage = event.usage
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, "content", None)
            think = getattr(delta, "reasoning_content", None)
            if think:
                reasoning.append(think)
            if piece or think:
                if ttft is None:
                    ttft = time.monotonic() - start
            if piece:
                chunks.append(piece)
        latency = time.monotonic() - start
        text = "".join(chunks)
        reasoning_text = "".join(reasoning)
        # Prefer server usage; else estimate from generated chars (content + reasoning).
        ct = getattr(usage, "completion_tokens", None)
        if not ct:
            ct = (len(text) + len(reasoning_text)) // 4 or None
        decode_window = (latency - ttft) if ttft else latency
        tps = (ct / decode_window) if (ct and decode_window and decode_window > 0) else None
        return ChatResult(
            text=text,
            model=model,
            ttft=ttft,
            latency=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=ct,
            tokens_per_sec=tps,
            reasoning_chars=len(reasoning_text),
            had_reasoning=bool(reasoning_text),
        )

    # ---- embeddings ------------------------------------------------------

    def embed(self, model: str, inputs: Iterable[str], **extra: Any):
        self.limiter.wait()
        return self._client.embeddings.create(
            model=model, input=list(inputs), **extra
        )

    # ---- image generation (genai host) ----------------------------------

    def generate_image(
        self,
        model: str,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg_scale: float = 3.5,
        seed: int = 0,
        timeout: float = 180.0,
    ) -> "ImageResult":
        """Text-to-image via the NVIDIA genai endpoint (separate from the chat host).

        Returns decoded PNG bytes plus latency. FLUX-family models accept widths/
        heights in {768,832,896,960,1024,1088,1152,1216,1280,1344}.
        """
        self.limiter.wait()
        url = f"{config.GENAI_BASE_URL}/{model}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {
            "prompt": prompt,
            "mode": "base",
            "cfg_scale": cfg_scale,
            "width": width,
            "height": height,
            "seed": seed,
            "steps": steps,
            "samples": 1,
        }
        if "flux.2" in model:  # FLUX.2 rejects `mode`, cfg_scale>1; steps<=4 (measured 2026-10-18)
            body.pop("mode"); body.pop("cfg_scale"); body["steps"] = min(steps, 4)
        start = time.monotonic()
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=timeout)
            latency = time.monotonic() - start
            if r.status_code != 200:
                err = f"HTTP {r.status_code}: {r.text[:160]}"
                telemetry.record(model, False, err, latency, kind="image")
                return ImageResult(model=model, ok=False, latency=latency, error=err)
            data = r.json()
            b64 = None
            if isinstance(data.get("artifacts"), list) and data["artifacts"]:
                b64 = data["artifacts"][0].get("base64")
            elif "image" in data:
                b64 = data["image"]
            if not b64:
                return ImageResult(model=model, ok=False, latency=latency,
                                   error=f"no image in response: {str(data)[:120]}")
            img = base64.b64decode(b64)
            telemetry.record(model, True, None, latency, kind="image")
            return ImageResult(model=model, ok=True, latency=latency, image=img,
                               width=width, height=height)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            telemetry.record(model, False, err, time.monotonic() - start, kind="image")
            return ImageResult(model=model, ok=False,
                               latency=time.monotonic() - start, error=err)


def _tool_calls_as_dicts(message: Any) -> list[dict]:
    """Normalise SDK tool-call objects (or raw dicts) into plain dicts.

    Kept defensive: NIM-hosted models vary in how faithfully they populate the
    OpenAI tool-call shape, and a malformed call is a result to record, not an
    exception to raise.
    """
    calls = getattr(message, "tool_calls", None) or []
    out: list[dict] = []
    for tc in calls:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            out.append({"id": tc.get("id"), "type": tc.get("type", "function"),
                        "function": {"name": fn.get("name"),
                                     "arguments": fn.get("arguments")}})
            continue
        fn = getattr(tc, "function", None)
        out.append({
            "id": getattr(tc, "id", None),
            "type": getattr(tc, "type", "function"),
            "function": {
                "name": getattr(fn, "name", None),
                "arguments": getattr(fn, "arguments", None),
            },
        })
    return out


# ---- multimodal helpers --------------------------------------------------


def image_data_url(path: str | Path) -> str:
    """Encode a local image file as a data: URL for vision chat messages."""
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def vision_message(text: str, image: str | Path, is_url: bool = False) -> dict:
    """Build an OpenAI-style multimodal user message (text + one image)."""
    url = str(image) if is_url else image_data_url(image)
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": url}},
        ],
    }
