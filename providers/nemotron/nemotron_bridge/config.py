"""Central configuration and API-key resolution.

The NVIDIA API key is read from the environment only — never hard-coded, never
logged. `NVIDIA_API_KEY` is preferred; `NGC_API_KEY` is a fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# OpenAI-compatible cloud endpoint for build.nvidia.com / NIM.
BASE_URL = "https://integrate.api.nvidia.com/v1"

# Image generation and some multimodal models live on a separate genai host.
GENAI_BASE_URL = "https://ai.api.nvidia.com/v1/genai"

# Free-tier rate limit (requests/min) as documented; empirically verifiable.
DEFAULT_RPM = 40

# Repo-relative locations.
REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO_ROOT / "models.yaml"
BATTERY_DIR = REPO_ROOT / "battery"
RESULTS_DIR = REPO_ROOT / "results"
SCORECARD_DIR = RESULTS_DIR / "scorecards"


class MissingKeyError(RuntimeError):
    """Raised when no NVIDIA API key is found in the environment."""


def get_api_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NGC_API_KEY")
    if not key:
        raise MissingKeyError(
            "No NVIDIA API key found. Set NVIDIA_API_KEY (preferred) or "
            "NGC_API_KEY. Get a free key at https://build.nvidia.com/settings/api-keys"
        )
    return key


def redact(key: str) -> str:
    """Return a safe-to-log fingerprint of a key (never the key itself)."""
    if not key:
        return "<none>"
    return f"{key[:6]}…{key[-4:]} (len {len(key)})"


@dataclass(frozen=True)
class Endpoints:
    chat: str = f"{BASE_URL}/chat/completions"
    models: str = f"{BASE_URL}/models"
    embeddings: str = f"{BASE_URL}/embeddings"
    genai: str = GENAI_BASE_URL
