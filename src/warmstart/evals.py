"""Offline engineering regression. This does not assess live model quality."""

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from warmstart.config import Config, fingerprint
from warmstart.core import WarmstartService
from warmstart.data import PROFILES, PROVENANCE, corpus_fingerprint, seeds
from warmstart.guards import classify
from warmstart.inference import OfflineInference, answer_for
from warmstart.models import AnswerRequest, Identity
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "golden.public.jsonl"
MANIFEST = ROOT / "data" / "fixtures.manifest.json"


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    family_id: str
    split: Literal["development", "regression"]
    category: str
    question: str
    profile: str
    policy_version: Literal["v1", "v2"]
    expected_outcome: Literal["answer", "bypass", "clarification"]
    reuse_allowed: bool
    acceptable_seed_ids: list[str]
    required_facts: list[str]
    forbidden_claims: list[str]
    warmup_previous_version: bool
    review_status: Literal["agent_authored_draft", "human_reviewed"]
    provenance: str


def load_cases(path: Path = DATA) -> list[GoldenCase]:
    cases = [GoldenCase.model_validate_json(line) for line in path.read_text().splitlines() if line]
    ids: set[str] = set()
    families: dict[str, str] = {}
    questions: dict[str, str] = {}
    seed_by_id = {seed.id: seed for seed in seeds()}
    for case in cases:
        if case.case_id in ids:
            raise ValueError(f"Duplicate case ID: {case.case_id}")
        ids.add(case.case_id)
        if families.setdefault(case.family_id, case.split) != case.split:
            raise ValueError(f"Family crosses splits: {case.family_id}")
        normalized_question = " ".join(case.question.casefold().split())
        if questions.setdefault(normalized_question, case.split) != case.split:
            raise ValueError(f"Identical question crosses splits: {case.case_id}")
        if case.profile not in PROFILES:
            raise ValueError(f"Unknown profile: {case.case_id}")
        if case.expected_outcome == "answer" and not case.required_facts:
            raise ValueError(f"Answer case lacks expected facts: {case.case_id}")
        if not case.reuse_allowed and case.acceptable_seed_ids:
            raise ValueError(f"Uncacheable case approves a seed: {case.case_id}")
        for seed_id in case.acceptable_seed_ids:
            seed = seed_by_id.get(seed_id)
            if seed is None or (seed.profile, seed.version) != (case.profile, case.policy_version):
                raise ValueError(f"Invalid scoped seed reference: {case.case_id}")
    return cases


def fixture_payload() -> dict[str, object]:
    source_root = Path(__file__).parent
    return {
        "format": "warmstart-offline-fixture-v1",
        "config": asdict(Config()),
        "corpus_sha256": corpus_fingerprint(),
        "golden_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "offline_algorithms_sha256": {
            name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
            for name in ("guards.py", "inference.py")
        },
        "provenance": PROVENANCE,
    }


def verify_manifest() -> None:
    recorded = json.loads(MANIFEST.read_text())
    actual = fingerprint(fixture_payload())
    if recorded.get("fingerprint") != actual:
        raise ValueError(
            "Fixture fingerprint mismatch: review policy/config/algorithm/data changes and "
            "update the manifest explicitly; do not regenerate golden labels."
        )


async def evaluate(
    suite: str,
    *,
    require_human_reviewed: bool = False,
    requests: int | None = None,
) -> dict[str, object]:
    verify_manifest()
    all_cases = load_cases()
    cases = [case for case in all_cases if case.split == suite]
    if not cases:
        raise ValueError("Selected suite is empty")
    if require_human_reviewed and any(case.review_status != "human_reviewed" for case in cases):
        raise ValueError("Human review gate failed: draft cases remain")
    unique_cases = len(cases)
    if requests is not None:
        if requests < unique_cases or requests > 10000:
            raise ValueError("Replay requests must cover the suite and be at most 10000")
        cases = [cases[index % unique_cases] for index in range(requests)]
    identity = Identity("offline-evaluation", frozenset(PROFILES), owner=True)
    conditions: dict[str, object] = {}
    for name in ("no_cache", "exact", "semantic", "template"):
        config = Config(
            exact_enabled=name != "no_cache",
            semantic_mode=("serve" if name == "semantic" else "off"),
        )
        store = SQLiteStore()
        coordinator = SQLiteCoordinator(identity_daily_limit=10000, global_daily_limit=10000)
        inference = OfflineInference()
        service = WarmstartService(store, coordinator, inference, config)
        failures: list[dict[str, str]] = []
        counts: dict[str, int] = {}
        semantic_hits = 0
        wrong_semantic_hits = 0
        safe_misses = 0
        timings: list[float] = []
        timings_by_status: dict[str, list[float]] = {}
        warmup_generations = 0
        warmup_embeddings = 0
        try:
            for case in cases:
                request = AnswerRequest(question=case.question, profile=case.profile)
                if case.warmup_previous_version:
                    await service.invalidate(identity, "v1")
                    before = inference.generation_calls
                    before_embed = inference.embedding_calls
                    if name != "template":
                        await service.answer(identity, request)
                    warmup_generations += inference.generation_calls - before
                    warmup_embeddings += inference.embedding_calls - before_embed
                await service.invalidate(identity, case.policy_version)
                started = time.perf_counter()
                if name == "template":
                    policy = await store.policy(case.profile, case.policy_version)
                    if policy is None:
                        raise ValueError("Template policy missing")
                    classification = classify(case.question)
                    if classification.safe:
                        answer, fact_ids = answer_for(policy, classification)
                        status = "template"
                    else:
                        answer, fact_ids = "", ()
                        status = (
                            "bypass"
                            if classification.intent in ("personal", "unsupported")
                            else "clarification"
                        )
                    version = policy.version
                else:
                    # Expected labels stay in this evaluator; only question/profile reach runtime.
                    result = await service.answer(identity, request)
                    answer, fact_ids = result.answer, tuple(result.source_ids)
                    status, version = result.cache_status, result.policy_version
                timings.append((time.perf_counter() - started) * 1000)
                timings_by_status.setdefault(status, []).append(timings[-1])
                counts[status] = counts.get(status, 0) + 1
                accepted = status in ("exact", "semantic")
                approved_sources = {
                    source
                    for seed in seeds()
                    if seed.id in case.acceptable_seed_ids
                    for source in seed.fact_ids
                }
                correct = (
                    version == case.policy_version
                    and all(fact in answer for fact in case.required_facts)
                    and not any(claim in answer for claim in case.forbidden_claims)
                    and (
                        (
                            status in ("generated", "exact", "semantic", "template")
                            and bool(fact_ids)
                        )
                        if case.expected_outcome == "answer"
                        else status == case.expected_outcome
                    )
                    and (not accepted or case.reuse_allowed)
                    and (not accepted or set(fact_ids).issubset(approved_sources))
                )
                if status == "semantic":
                    semantic_hits += 1
                    wrong_semantic_hits += int(not correct)
                if case.reuse_allowed and status == "generated":
                    safe_misses += 1
                if not correct:
                    failures.append({"case_id": case.case_id, "status": status})
            ordered = sorted(timings)
            conditions[name] = {
                "cases": len(cases),
                "correct": len(cases) - len(failures),
                "failures": failures,
                "counts": counts,
                "safe_misses": safe_misses,
                "semantic_hits": semantic_hits,
                "incorrect_semantic_hits": wrong_semantic_hits,
                "zero_error_upper_95_if_iid": (
                    round(1 - 0.05 ** (1 / semantic_hits), 6)
                    if semantic_hits and not wrong_semantic_hits
                    else None
                ),
                "generation_calls": inference.generation_calls - warmup_generations,
                "embedding_calls": inference.embedding_calls - warmup_embeddings,
                "warmup_generations": warmup_generations,
                "warmup_embeddings": warmup_embeddings,
                "local_fixture_latency_ms": {
                    "p50": round(statistics.median(timings), 3),
                    "p95": round(ordered[max(0, math_ceil_95(len(ordered)) - 1)], 3),
                },
                "local_fixture_latency_by_status_ms": {
                    status: {
                        "p50": round(statistics.median(values), 3),
                        "p95": round(sorted(values)[math_ceil_95(len(values)) - 1], 3),
                    }
                    for status, values in timings_by_status.items()
                },
                "pass": not failures,
            }
        finally:
            store.close()
            coordinator.close()
    return {
        "suite": suite,
        "mode": "replay",
        "fixture_fingerprint": fingerprint(fixture_payload()),
        "dataset_cases": len(all_cases),
        "selected_cases": len(cases),
        "unique_selected_cases": unique_cases,
        "traffic_order": "public file order repeated cyclically; no shuffle",
        "initial_state": "empty exact cache, loaded fixture seeds, v1 policy, per-condition reset",
        "human_reviewed_cases": sum(
            case.review_status == "human_reviewed" for case in all_cases if case.split == suite
        ),
        "fixture_seed_count": len(seeds()),
        "human_approved_seeds": sum(seed.human_approved for seed in seeds()),
        "limitations": [
            "Agent-authored draft labels; human review is pending.",
            "Feature-hash vectors and deterministic policy outputs are not live model evidence.",
            "No paid provider cost or hosted latency measured.",
            "No private holdout exists or was accessed.",
            "Repeated traffic does not increase unique question or human-review evidence.",
            "The optional IID bound is illustrative; synthetic repeated cases are dependent.",
            "Event costs are confirmed/estimated usage, not the ledger's uncertain reservations.",
        ],
        "conditions": conditions,
        "pass": all(isinstance(value, dict) and value["pass"] for value in conditions.values()),
        "production_promotion_eligible": False,
    }


def math_ceil_95(count: int) -> int:
    return (95 * count + 99) // 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("development", "regression"), default="regression")
    parser.add_argument("--mode", choices=("replay",), default="replay")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-human-reviewed", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--requests", type=int, help="Ordered traffic count; repeats this split")
    args = parser.parse_args()
    try:
        if args.validate_only:
            verify_manifest()
            cases = load_cases()
            report: dict[str, object] = {"pass": True, "validated_cases": len(cases)}
        else:
            report = asyncio.run(
                evaluate(
                    args.suite,
                    require_human_reviewed=args.require_human_reviewed,
                    requests=args.requests,
                )
            )
    except (ValueError, OSError) as exc:
        print(json.dumps({"pass": False, "error": str(exc)}))
        raise SystemExit(1) from exc
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    print(payload)
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
