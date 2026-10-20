"""Explicit behavior settings; fingerprints invalidate incompatible recordings."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Literal


def fingerprint(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class Config:
    environment: Literal["local", "staging", "pilot"] = "local"
    semantic_mode: Literal["off", "shadow", "serve"] = "shadow"
    exact_enabled: bool = True
    paid_inference: bool = False
    allow_fixture_seeds: bool = True
    ttl_seconds: float = 86400
    semantic_threshold: float = 0.88
    generation_model: str = "offline-policy-fixture-v1"
    embedding_model: str = "offline-feature-hash-384-v1"
    embedding_dimensions: int = 384
    embedding_pooling: str = "offline-token-hash"
    embedding_normalization: str = "l2"
    prompt_version: str = "support-json-v1"
    schema_version: str = "answer-v1"
    temperature: float = 0
    max_output_tokens: int = 512
    reasoning_effort: str = "low"
    embedding_reservation_microusd: int = 100
    generation_reservation_microusd: int = 10000
    deadline_seconds: float = 20
    duplicate_wait_seconds: float = 2
    lease_seconds: float = 25

    def __post_init__(self) -> None:
        if self.environment not in ("local", "staging", "pilot"):
            raise ValueError("Unknown environment")
        if self.semantic_mode not in ("off", "shadow", "serve"):
            raise ValueError("Unknown semantic mode")
        if self.environment != "local" and self.allow_fixture_seeds:
            raise ValueError("Nonlocal serving requires human-approved seeds, not fixture approval")
        if not math.isfinite(self.semantic_threshold) or not 0 <= self.semantic_threshold <= 1:
            raise ValueError("Semantic threshold must be between zero and one")
        if any(
            not math.isfinite(value) or value <= 0
            for value in (
                self.ttl_seconds,
                self.deadline_seconds,
                self.lease_seconds,
            )
        ):
            raise ValueError("TTL and deadline must be positive")
        if self.lease_seconds <= self.deadline_seconds:
            raise ValueError("A generation lease must outlive the request deadline")
        if self.embedding_dimensions != 384:
            raise ValueError("The initial search contract uses 384-dimensional vectors")

    def signature(self, profile: str, version: str) -> str:
        compatibility = asdict(self)
        # Disabling paid work must preserve valid private exact entries. Content,
        # provenance, TTL and admission thresholds still bind response compatibility.
        # Full configuration remains in evaluation and release fingerprints.
        for name in (
            "paid_inference",
            "exact_enabled",
            "semantic_mode",
            "deadline_seconds",
            "duplicate_wait_seconds",
            "lease_seconds",
            "embedding_reservation_microusd",
            "generation_reservation_microusd",
        ):
            del compatibility[name]
        return fingerprint({"config": compatibility, "profile": profile, "policy": version})

    def embedding_fingerprint(self) -> str:
        return fingerprint(
            {
                "model": self.embedding_model,
                "dimensions": self.embedding_dimensions,
                "pooling": self.embedding_pooling,
                "normalization": self.embedding_normalization,
            }
        )
