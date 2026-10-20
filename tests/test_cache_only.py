from dataclasses import replace

import pytest

from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.data import PROFILES
from warmstart.inference import OfflineInference
from warmstart.models import AnswerRequest, BudgetExceeded, Identity
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore


async def test_paid_kill_switch_preserves_private_exact_hits_and_blocks_new_calls():
    class PaidFixture(OfflineInference):
        paid = True

    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), PaidFixture()
    service = WarmstartService(
        store, coordinator, inference, Config(paid_inference=True, semantic_mode="off")
    )
    identity = Identity("tester", frozenset(PROFILES))
    request = AnswerRequest(question="What is the standard shipping cost?")
    try:
        assert (await service.answer(identity, request)).cache_status == "generated"
        before = service.config.signature(request.profile, "v1")
        service.config = replace(service.config, paid_inference=False, deadline_seconds=15)
        assert service.config.signature(request.profile, "v1") == before
        assert (await service.answer(identity, request)).cache_status == "exact"
        with pytest.raises(BudgetExceeded):
            await service.answer(identity, AnswerRequest(question="What is the delivery fee?"))
        assert inference.generation_calls == 1 and inference.embedding_calls == 0
    finally:
        store.close()
        coordinator.close()


@pytest.mark.parametrize(
    "question",
    [
        "What is shipping cost for standard profile?",
        "What is shipping cost for standard customers?",
        "What is premium shipping cost?",
        "What is the return fee for unopened products?",
    ],
)
async def test_incompatible_tier_service_and_question_type_never_call_inference(question):
    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), OfflineInference()
    service = WarmstartService(store, coordinator, inference, Config(semantic_mode="serve"))
    try:
        result = await service.answer(
            Identity("tester", frozenset(PROFILES)),
            AnswerRequest(question=question, profile="store_a_ch_premium"),
        )
        assert result.cache_status == "clarification" and result.source_ids == []
        assert inference.generation_calls == 0 and inference.embedding_calls == 0
    finally:
        store.close()
        coordinator.close()
