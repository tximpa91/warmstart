import asyncio

import pytest

from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.inference import OfflineInference
from warmstart.models import AnswerRequest, Identity, WarmstartError
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore


async def test_stalled_admission_is_bounded_and_calls_no_provider():
    store, coordinator, inference = SQLiteStore(), SQLiteCoordinator(), OfflineInference()

    async def slow(*args):
        await asyncio.sleep(1)

    coordinator.admit = slow
    service = WarmstartService(store, coordinator, inference, Config(deadline_seconds=0.01))
    try:
        with pytest.raises(WarmstartError, match="timed out"):
            await service.answer(
                Identity("tester", frozenset({"store_a_ch_standard"})),
                AnswerRequest(question="What is the shipping cost?"),
            )
        assert inference.generation_calls == 0
    finally:
        store.close()
        coordinator.close()
