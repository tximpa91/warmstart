"""Credential-free deterministic fixtures, not a real embedding or model benchmark."""

import hashlib
import math
import re

from warmstart.guards import classify
from warmstart.models import (
    Classification,
    EmbeddingResult,
    GenerationResult,
    Policy,
    Usage,
)


def offline_vector(question: str) -> tuple[float, ...]:
    """Feature hashing deliberately exposes its rules; never label these BGE vectors."""
    classification = classify(question)
    vector = [0.0] * 384
    # Domain features make reproducible contract fixtures; they do not prove semantic quality.
    features = [f"guard:{classification.guard}"] * 20
    features += re.findall(r"[a-z]+", question.casefold())
    for token in features:
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % 384
        vector[index] += 1.0
    length = math.sqrt(sum(value * value for value in vector)) or 1
    return tuple(value / length for value in vector)


def answer_for(policy: Policy, classification: Classification) -> tuple[str, tuple[str, ...]]:
    key = classification.guard
    if key not in policy.facts:
        raise ValueError("Unsupported fixture intent")
    return policy.facts[key], (policy.source_ids[key],)


class OfflineInference:
    """No network, no API keys and no paid calls. Output is fictional policy text."""

    paid = False

    def __init__(self) -> None:
        self.embedding_calls = 0
        self.generation_calls = 0

    async def embed(self, question: str) -> EmbeddingResult:
        self.embedding_calls += 1
        return EmbeddingResult(offline_vector(question), Usage(input_tokens=len(question.split())))

    async def generate(
        self, question: str, policy: Policy, classification: Classification
    ) -> GenerationResult:
        self.generation_calls += 1
        answer, fact_ids = answer_for(policy, classification)
        return GenerationResult(
            answer,
            fact_ids,
            Usage(input_tokens=len(question.split()), output_tokens=len(answer.split())),
        )
