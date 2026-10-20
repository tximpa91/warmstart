"""Record original offline demo responses; no credentials or live inference."""

import asyncio
import json
from pathlib import Path

from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.data import PROFILES
from warmstart.inference import OfflineInference
from warmstart.models import AnswerRequest, Identity
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore


async def record() -> list[dict]:
    store, coordinator = SQLiteStore(), SQLiteCoordinator()
    service = WarmstartService(store, coordinator, OfflineInference(), Config(semantic_mode="off"))
    identity = Identity("public-fixture-only", frozenset(PROFILES))
    results = []
    try:
        for profile in ("store_a_ch_standard", "store_a_ch_premium", "store_b_ch_standard"):
            for question in (
                "What is the standard shipping cost?",
                "How long can I return unopened products?",
                "Can I return opened headphones?",
                "my order status",
            ):
                request = AnswerRequest(question=question, profile=profile)
                first = await service.answer(identity, request)
                second = await service.answer(identity, request)
                results.append(
                    {
                        "profile": profile,
                        "question": question,
                        "first": first.model_dump(exclude={"request_id"}),
                        "second": second.model_dump(exclude={"request_id"}),
                    }
                )
    finally:
        store.close()
        coordinator.close()
    return results


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "public/recordings.json"
    target.write_text(json.dumps(asyncio.run(record()), indent=2) + "\n")
    print("Recorded 12 fictional examples. Human review pending.")
