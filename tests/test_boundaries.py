import asyncio
from dataclasses import replace

import pytest

from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.data import PROFILES
from warmstart.guards import classify
from warmstart.inference import OfflineInference
from warmstart.models import AnswerRequest, Identity, InvalidInference, WarmstartError
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore


@pytest.mark.parametrize(
    "question",
    [
        "What is the overnight shipping cost?",
        "What is the shipping cost to France?",
        "How long is warranty for refurbished laptops?",
        "What is express shipping cost?",
        "Can I return opened headphones and an unopened charger?",
        "How long is refund processing and what is shipping cost?",
        "What is the shipping cost to 中国?",
        "What is the return fee for unopened products?",
        "What is premium shipping cost?",
        "How long does standard shipping take?",
        "What is unopened product return processing time?",
        "How long is warranty for opened headphones?",
    ],
)
def test_unsupported_qualifications_and_mixed_conditions_clarify(question):
    assert not classify(question).safe


async def test_telemetry_and_release_failure_do_not_mask_valid_answer():
    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), OfflineInference()

    async def unavailable(*args):
        raise OSError("storage unavailable")

    store.event = unavailable
    coordinator.release = unavailable
    service = WarmstartService(store, coordinator, inference, Config(semantic_mode="off"))
    result = await service.answer(
        Identity("tester", frozenset(PROFILES)),
        AnswerRequest(question="What is the shipping cost?"),
    )
    assert result.cache_status == "generated"
    store.close()
    coordinator.close()


async def test_timeout_retains_reservation_and_releases_lease():
    class SlowPaid(OfflineInference):
        paid = True

        async def generate(self, *args):
            await asyncio.sleep(1)

    store, coordinator = SQLiteStore(), SQLiteCoordinator()
    service = WarmstartService(
        store,
        coordinator,
        SlowPaid(),
        Config(paid_inference=True, semantic_mode="off", deadline_seconds=0.01),
    )
    with pytest.raises(WarmstartError):
        await service.answer(
            Identity("tester", frozenset(PROFILES)),
            AnswerRequest(question="What is the shipping cost?"),
        )
    state = await coordinator.state()
    assert state["spending"][0]["committed_microusd"] == 10000
    assert coordinator.connection.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
    store.close()
    coordinator.close()


async def test_coordinator_failure_calls_no_provider():
    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), OfflineInference()

    async def unavailable(*args):
        raise WarmstartError()

    coordinator.reserve = unavailable
    service = WarmstartService(store, coordinator, inference, Config(semantic_mode="off"))
    with pytest.raises(WarmstartError):
        await service.answer(
            Identity("tester", frozenset(PROFILES)),
            AnswerRequest(question="What is the shipping cost?"),
        )
    assert inference.generation_calls == 0 and inference.embedding_calls == 0
    store.close()
    coordinator.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt_version", "new-prompt"),
        ("schema_version", "new-schema"),
        ("generation_model", "new-model"),
        ("temperature", 0.5),
    ],
)
async def test_configuration_change_invalidates_exact(field, value):
    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), OfflineInference()
    service = WarmstartService(store, coordinator, inference, Config(semantic_mode="off"))
    identity, request = (
        Identity("tester", frozenset(PROFILES)),
        AnswerRequest(question="What is the shipping cost?"),
    )
    await service.answer(identity, request)
    assert (await service.answer(identity, request)).cache_status == "exact"
    service.config = replace(service.config, **{field: value})
    assert (await service.answer(identity, request)).cache_status == "generated"
    store.close()
    coordinator.close()


async def test_wrong_fact_for_valid_policy_rejected():
    from warmstart.models import GenerationResult

    class WrongFact(OfflineInference):
        async def generate(self, question, policy, classification):
            return GenerationResult(
                policy.facts["refund:standard"], (policy.source_ids["refund:standard"],)
            )

    store, coordinator = SQLiteStore(), SQLiteCoordinator()
    service = WarmstartService(store, coordinator, WrongFact(), Config(semantic_mode="off"))
    with pytest.raises(InvalidInference):
        await service.answer(
            Identity("tester", frozenset(PROFILES)),
            AnswerRequest(question="What is the shipping cost?"),
        )
    store.close()
    coordinator.close()
