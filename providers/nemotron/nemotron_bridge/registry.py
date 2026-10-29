"""Model registry: self-seed from the live catalog, infer modality, merge overrides.

The NVIDIA `/v1/models` response carries no capability metadata (only id and
owner), so modality is inferred from the model id and then refined by a curated
`models.yaml` overrides file. The catalog changes weekly, so the registry is
always reconciled against the live list rather than hand-maintained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import config
from .client import NemotronClient

# Probe-selecting transport categories.
CHAT = "chat"
VISION = "vision"          # image-in, text-out (VLMs)
CODE = "code"              # code-specialized chat
EMBEDDING = "embedding"
IMAGE_GEN = "image-gen"    # text-in, image-out (mostly on genai host)
RERANK = "rerank"          # rerank / doc-parse / retrieval
GUARD = "guard"            # safety classifiers / guardrails
REWARD = "reward"          # reward models
TRANSLATE = "translate"
OTHER = "other"

# Modalities the assessment battery runs against by default.
ASSESSABLE = {CHAT, VISION, CODE}

# Ordered (first match wins) substring rules for modality inference.
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("nemoguard", "content-safety", "safety-guard", "topic-control", "llama-guard"), GUARD),
    (("reward",), REWARD),
    (("riva-translate",), TRANSLATE),
    (("embed", "embedqa", "arctic-embed", "bge-"), EMBEDDING),
    (("parse", "chatqa"), RERANK),
    (("diffusion",), IMAGE_GEN),
    (("-vl-", "-vl", "vila", "neva", "fuyu", "kosmos", "deplot", "vision",
      "cosmos-reason", "nvclip", "omni", "phi-3-vision"), VISION),
    (("coder", "code", "codestral", "starcoder", "codegemma", "codellama", "laguna"), CODE),
]


def infer_modality(model_id: str) -> str:
    mid = model_id.lower()
    for needles, modality in _RULES:
        if any(n in mid for n in needles):
            return modality
    return CHAT


# Image-generation models live on the genai host, not in /v1/models, so they are
# seeded explicitly. Only those confirmed callable on the free tier are listed.
GENAI_SEED = [
    "black-forest-labs/flux.2-klein-4b",
    "black-forest-labs/flux.1-dev",
    "black-forest-labs/flux.1-schnell",
    "black-forest-labs/flux.1-kontext-dev",
]


@dataclass
class ModelEntry:
    id: str
    owner: str = ""
    modality: str = CHAT
    reasoning: bool = False          # exposes a reasoning/thinking mode
    context: int | None = None       # context window (tokens), if known
    tier_hint: str | None = None     # curated nearest-Anthropic guess pre-assessment
    notes: str = ""
    endpoint: str = ""               # "" = chat host; "genai" = image host
    assess: bool = True              # include in the assessment battery
    seen_live: bool = True           # present in last live catalog fetch

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "", False) or k == "id"}


@dataclass
class Registry:
    entries: dict[str, ModelEntry] = field(default_factory=dict)

    # ---- construction ----------------------------------------------------

    @classmethod
    def load(cls, path: Path = config.REGISTRY_PATH) -> "Registry":
        reg = cls()
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            for item in data.get("models", []):
                reg.entries[item["id"]] = ModelEntry(**item)
        return reg

    def refresh_from_live(self, client: NemotronClient | None = None) -> tuple[int, int]:
        """Reconcile against the live catalog. Returns (added, total_live)."""
        client = client or NemotronClient()
        live_ids = client.list_models()
        added = 0
        live_set = set(live_ids)
        for mid in live_ids:
            if mid not in self.entries:
                owner = mid.split("/", 1)[0] if "/" in mid else ""
                self.entries[mid] = ModelEntry(
                    id=mid,
                    owner=owner,
                    modality=infer_modality(mid),
                    assess=infer_modality(mid) in ASSESSABLE,
                )
                added += 1
            else:
                self.entries[mid].seen_live = True
        for mid, entry in self.entries.items():
            entry.seen_live = mid in live_set
        # Seed genai image-gen models (not present in /v1/models).
        for mid in GENAI_SEED:
            if mid not in self.entries:
                self.entries[mid] = ModelEntry(
                    id=mid, owner=mid.split("/", 1)[0], modality=IMAGE_GEN,
                    endpoint="genai", assess=True,
                )
                added += 1
            self.entries[mid].seen_live = True
        return added, len(live_ids)

    # ---- persistence -----------------------------------------------------

    def save(self, path: Path = config.REGISTRY_PATH) -> None:
        ordered = sorted(self.entries.values(), key=lambda e: (e.modality, e.id))
        payload = {"models": [e.to_dict() for e in ordered]}
        path.write_text(
            "# Auto-reconciled from GET /v1/models; hand-edit fields freely — they are\n"
            "# preserved on refresh. Only `id` is required per entry.\n"
            + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        )

    # ---- queries ---------------------------------------------------------

    def by_modality(self, modality: str) -> list[ModelEntry]:
        return sorted(
            (e for e in self.entries.values() if e.modality == modality and e.seen_live),
            key=lambda e: e.id,
        )

    def assessable(self) -> list[ModelEntry]:
        # Filter by modality (chat/code/vision) rather than the `assess` flag:
        # the flag round-trips unreliably through YAML (False is dropped), and
        # the text/vision battery is only meaningful for these modalities anyway.
        return sorted(
            (e for e in self.entries.values() if e.modality in ASSESSABLE and e.seen_live),
            key=lambda e: e.id,
        )

    def get(self, model_id: str) -> ModelEntry | None:
        return self.entries.get(model_id)
