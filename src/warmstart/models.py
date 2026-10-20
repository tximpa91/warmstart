"""Portable contracts. No database or Cloudflare imports belong here."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Identity:
    subject: str
    allowed_profiles: frozenset[str]
    owner: bool = False


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=1000)
    profile: str = Field(default="store_a_ch_standard", pattern=r"^[a-z0-9_]{1,64}$")


class AnswerResponse(BaseModel):
    answer: str
    source_ids: list[str]
    cache_status: Literal["exact", "semantic", "generated", "bypass", "clarification"]
    policy_version: str
    request_id: str
    semantic_shadow_match: bool = False


class InvalidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_version: Literal["v1", "v2"]


@dataclass(frozen=True)
class Classification:
    intent: str
    condition: str
    safe: bool
    reason: str = ""

    @property
    def guard(self) -> str:
        return f"{self.intent}:{self.condition}"


@dataclass(frozen=True)
class Policy:
    profile: str
    version: str
    facts: dict[str, str]
    source_ids: dict[str, str]


@dataclass(frozen=True)
class SeedAnswer:
    id: str
    profile: str
    version: str
    question: str
    guard: str
    answer: str
    fact_ids: tuple[str, ...]
    vector: tuple[float, ...]
    fixture_approved: bool = True
    human_approved: bool = False
    embedding_fingerprint: str = ""
    reviewed_at: float | None = None
    expires_at: float | None = None


@dataclass(frozen=True)
class CachedAnswer:
    key: str
    answer: str
    fact_ids: tuple[str, ...]
    version: str
    expires_at: float
    signature: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_microusd: int = 0
    estimated: bool = False


@dataclass(frozen=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    fact_ids: tuple[str, ...]
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class Admission:
    version: str
    request_id: str


@dataclass(frozen=True)
class RequestEvent:
    request_id: str
    subject_hash: str
    profile: str
    version: str
    status: str
    latency_ms: float
    cost_microusd: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    shadow_match: bool
    usage_estimated: bool = False


class WarmstartError(Exception):
    status_code = 503
    code = "service_unavailable"


class Unauthorized(WarmstartError):
    status_code = 403
    code = "forbidden"


class BudgetExceeded(WarmstartError):
    status_code = 429
    code = "budget_exhausted"


class QuotaExceeded(WarmstartError):
    status_code = 429
    code = "quota_exhausted"


class Busy(WarmstartError):
    status_code = 503
    code = "busy"


class InvalidInference(WarmstartError):
    code = "invalid_inference"


class TransientInference(WarmstartError):
    """A provider error for which a bounded retry is appropriate."""

    code = "inference_unavailable"
