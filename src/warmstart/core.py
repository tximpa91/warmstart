"""Deterministic request orchestration shared by local Python and Workers."""

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from warmstart.config import Config, fingerprint
from warmstart.guards import classify, cosine, normalize
from warmstart.models import (
    Admission,
    AnswerRequest,
    AnswerResponse,
    BudgetExceeded,
    Busy,
    CachedAnswer,
    EmbeddingResult,
    GenerationResult,
    Identity,
    InvalidInference,
    RequestEvent,
    SeedAnswer,
    TransientInference,
    Unauthorized,
    Usage,
    WarmstartError,
)
from warmstart.ports import Clock, Coordinator, Inference, Store

T = TypeVar("T", EmbeddingResult, GenerationResult)
logger = logging.getLogger("warmstart")


def validate_usage(usage: Usage) -> None:
    values = (
        usage.input_tokens,
        usage.output_tokens,
        usage.cached_input_tokens,
        usage.cost_microusd,
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise InvalidInference("Invalid token/cost accounting")
    if usage.cached_input_tokens > usage.input_tokens:
        raise InvalidInference("Cached input cannot exceed total input")


class WarmstartService:
    def __init__(
        self,
        store: Store,
        coordinator: Coordinator,
        inference: Inference,
        config: Config | None = None,
        clock: Clock = time.time,
    ) -> None:
        self.store = store
        self.coordinator = coordinator
        self.inference = inference
        self.config = config or Config()
        self.clock = clock

    async def _operation(self, kind: str, call: Callable[[], Awaitable[T]]) -> T:
        if self.inference.paid and not self.config.paid_inference:
            raise BudgetExceeded("Paid inference is disabled")
        # Platform transport preflight occurs after exact lookup but before reserving
        # spend. Local fixture adapters need no gateway and keep their existing contract.
        validate_configuration = getattr(self.inference, "validate_configuration", None)
        if validate_configuration is not None:
            validate_configuration()
        amount = (
            self.config.embedding_reservation_microusd
            if kind == "embedding"
            else self.config.generation_reservation_microusd
        )
        reservation = await self.coordinator.reserve(kind, amount, self.clock())
        # Unknown outcomes retain their conservative reservation, including cancellation.
        result = await call()
        if not isinstance(result, (EmbeddingResult, GenerationResult)):
            raise InvalidInference("Unexpected inference response type")
        validate_usage(result.usage)
        await self.coordinator.settle(reservation, result.usage.cost_microusd)
        return result

    async def answer(self, identity: Identity, request: AnswerRequest) -> AnswerResponse:
        if request.profile not in identity.allowed_profiles:
            raise Unauthorized()
        started = time.monotonic()
        admission: Admission | None = None
        usages: list[Usage] = []
        status = "error"
        shadow_match = False
        try:
            async with asyncio.timeout(self.config.deadline_seconds):
                admission = await self.coordinator.admit(
                    fingerprint(identity.subject), self.clock()
                )
                response, usages = await self._answer(
                    identity, request, admission.version, admission.request_id, usages
                )
            status = response.cache_status
            shadow_match = response.semantic_shadow_match
            return response
        except TimeoutError as exc:
            raise WarmstartError("Inference request timed out") from exc
        finally:
            # Never record question text, identities, prompts, or provider payloads.
            if admission is not None:
                await self._cleanup(
                    self.store.event(
                        RequestEvent(
                            request_id=admission.request_id,
                            subject_hash=fingerprint(identity.subject),
                            profile=request.profile,
                            version=admission.version,
                            status=status,
                            latency_ms=round((time.monotonic() - started) * 1000, 3),
                            cost_microusd=sum(item.cost_microusd for item in usages),
                            input_tokens=sum(item.input_tokens for item in usages),
                            output_tokens=sum(item.output_tokens for item in usages),
                            cached_input_tokens=sum(item.cached_input_tokens for item in usages),
                            shadow_match=shadow_match,
                            usage_estimated=any(item.estimated for item in usages),
                        )
                    )
                )

    @staticmethod
    async def _cleanup(operation: Awaitable[None]) -> None:
        # Telemetry/lease cleanup must neither mask an answer nor extend its deadline.
        try:
            async with asyncio.timeout(0.25):
                await operation
        except Exception as exc:
            logger.warning("cleanup_failed type=%s", type(exc).__name__)

    async def _answer(
        self,
        identity: Identity,
        request: AnswerRequest,
        version: str,
        request_id: str,
        usages: list[Usage],
    ) -> tuple[AnswerResponse, list[Usage]]:
        policy = await self.store.policy(request.profile, version)
        if policy is None:
            raise WarmstartError("Admitted policy is unavailable")
        classification = classify(request.question)
        if "premium" in normalize(request.question) and not request.profile.endswith("_premium"):
            from warmstart.models import Classification

            classification = Classification("ambiguous", "", False, "tier_conflict")
        if any(
            phrase in normalize(request.question)
            for phrase in (
                "standard customers",
                "standard customer",
                "standard profile",
                "standard tier",
            )
        ) and request.profile.endswith("_premium"):
            from warmstart.models import Classification

            classification = Classification("ambiguous", "", False, "tier_conflict")
        if not classification.safe:
            personal = classification.intent in ("personal", "unsupported")
            return AnswerResponse(
                answer=(
                    "This demo cannot access orders, accounts, payments, or execute instructions."
                    if personal
                    else "Please specify the product condition and ask one policy question "
                    "about returns, shipping cost, refund time, or warranty duration."
                ),
                source_ids=[],
                cache_status="bypass" if personal else "clarification",
                policy_version=version,
                request_id=request_id,
            ), []

        signature = self.config.signature(request.profile, version)
        expected_sources = {policy.source_ids[classification.guard]}
        key = fingerprint(
            {
                "signature": signature,
                "owner": identity.subject,
                "question": normalize(request.question),
            }
        )
        if self.config.exact_enabled:
            cached = await self.store.exact_get(key, self.clock())
            if cached and cached.signature == signature and cached.version == version:
                self._validate_answer(cached.answer, cached.fact_ids, expected_sources)
                return AnswerResponse(
                    answer=cached.answer,
                    source_ids=list(cached.fact_ids),
                    cache_status="exact",
                    policy_version=version,
                    request_id=request_id,
                ), []

        shadow_match = False
        if self.config.semantic_mode != "off":
            try:
                embedded = await self._operation(
                    "embedding", lambda: self.inference.embed(request.question)
                )
                usages.append(embedded.usage)
                if len(embedded.vector) != self.config.embedding_dimensions or not all(
                    math.isfinite(value) for value in embedded.vector
                ):
                    raise InvalidInference("Invalid embedding")
                entries = await self.store.candidates(request.profile, version)
                # Filtering before ranking prevents irrelevant candidates from displacing safe ones.
                eligible = [
                    entry
                    for entry in entries
                    if entry.guard == classification.guard
                    and entry.profile == request.profile
                    and entry.version == version
                    and entry.embedding_fingerprint == self.config.embedding_fingerprint()
                    and (
                        (
                            entry.human_approved
                            and entry.reviewed_at is not None
                            and math.isfinite(entry.reviewed_at)
                            and entry.reviewed_at <= self.clock()
                            and entry.expires_at is not None
                            and math.isfinite(entry.expires_at)
                            and entry.expires_at > self.clock()
                        )
                        or (
                            self.config.environment == "local"
                            and self.config.allow_fixture_seeds
                            and entry.fixture_approved
                        )
                    )
                ]
                matches = sorted(
                    ((cosine(embedded.vector, entry.vector), entry) for entry in eligible),
                    key=lambda item: item[0],
                    reverse=True,
                )[:5]
                if matches and matches[0][0] >= self.config.semantic_threshold:
                    candidate = matches[0][1]
                    self._validate_seed(candidate, expected_sources)
                    shadow_match = True
                    if self.config.semantic_mode == "serve":
                        if self.config.exact_enabled:
                            expiry = self.clock() + self.config.ttl_seconds
                            if candidate.expires_at is not None:
                                expiry = min(expiry, candidate.expires_at)
                            await self.store.exact_put(
                                CachedAnswer(
                                    key,
                                    candidate.answer,
                                    candidate.fact_ids,
                                    version,
                                    expiry,
                                    signature,
                                )
                            )
                        return AnswerResponse(
                            answer=candidate.answer,
                            source_ids=list(candidate.fact_ids),
                            cache_status="semantic",
                            policy_version=version,
                            request_id=request_id,
                        ), usages
            except (InvalidInference, TransientInference, ValueError):
                # Embedding/provider failure causes a safe miss, never unrestricted reuse.
                pass

        token = await self.coordinator.acquire(key, self.clock(), self.config.lease_seconds)
        if token is None:
            # Polling is bounded by monotonic time even when the test clock is frozen.
            deadline = time.monotonic() + self.config.duplicate_wait_seconds
            while time.monotonic() < deadline:
                await asyncio.sleep(0.025)
                if self.config.exact_enabled:
                    cached = await self.store.exact_get(key, self.clock())
                    if cached and cached.signature == signature and cached.version == version:
                        self._validate_answer(cached.answer, cached.fact_ids, expected_sources)
                        return AnswerResponse(
                            answer=cached.answer,
                            source_ids=list(cached.fact_ids),
                            cache_status="exact",
                            policy_version=version,
                            request_id=request_id,
                            semantic_shadow_match=shadow_match,
                        ), usages
            raise Busy("Generation concurrency limit reached")
        try:
            # A predecessor may have filled the cache between lookup and lease acquisition.
            if self.config.exact_enabled:
                cached = await self.store.exact_get(key, self.clock())
                if cached and cached.signature == signature and cached.version == version:
                    self._validate_answer(cached.answer, cached.fact_ids, expected_sources)
                    return AnswerResponse(
                        answer=cached.answer,
                        source_ids=list(cached.fact_ids),
                        cache_status="exact",
                        policy_version=version,
                        request_id=request_id,
                        semantic_shadow_match=shadow_match,
                    ), usages
            generated: GenerationResult | None = None
            for attempt in range(2):
                try:
                    generated = await self._operation(
                        "generation",
                        lambda: self.inference.generate(request.question, policy, classification),
                    )
                    break
                except TransientInference:
                    if attempt == 1:
                        raise
            if generated is None:
                raise InvalidInference()
            usages.append(generated.usage)
            self._validate_answer(generated.answer, generated.fact_ids, expected_sources)
            if self.config.exact_enabled:
                await self.store.exact_put(
                    CachedAnswer(
                        key=key,
                        answer=generated.answer,
                        fact_ids=generated.fact_ids,
                        version=version,
                        expires_at=self.clock() + self.config.ttl_seconds,
                        signature=signature,
                    )
                )
            return AnswerResponse(
                answer=generated.answer,
                source_ids=list(generated.fact_ids),
                cache_status="generated",
                policy_version=version,
                request_id=request_id,
                semantic_shadow_match=shadow_match,
            ), usages
        finally:
            await self._cleanup(self.coordinator.release(key, token))

    @staticmethod
    def _validate_answer(answer: str, fact_ids: tuple[str, ...], sources: set[str]) -> None:
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > 6000
            or not fact_ids
            or len(fact_ids) > 10
            or not set(fact_ids).issubset(sources)
        ):
            raise InvalidInference("Answer does not satisfy the response contract")

    @classmethod
    def _validate_seed(cls, seed: SeedAnswer, sources: set[str]) -> None:
        cls._validate_answer(seed.answer, seed.fact_ids, sources)

    async def invalidate(self, identity: Identity, version: str) -> None:
        if not identity.owner:
            raise Unauthorized()
        # Verify every provisioned profile before publishing a global version pointer.
        from warmstart.data import PROFILES

        for profile in PROFILES:
            if await self.store.policy(profile, version) is None:
                raise WarmstartError("Target policy version is incomplete")
        await self.coordinator.activate(version)

    async def metrics(self, identity: Identity) -> dict[str, object]:
        if not identity.owner:
            raise Unauthorized()
        return {
            "requests": await self.store.metrics(),
            "coordinator": await self.coordinator.state(),
        }
