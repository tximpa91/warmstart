import json
from dataclasses import replace

import httpx
import pytest
from deploy_config import render

from warmstart.cloud import WorkersAIInference
from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.data import PROFILES, policies
from warmstart.gateway import GatewaySettings, validate_gateway_id
from warmstart.guards import classify
from warmstart.models import (
    AnswerRequest,
    BudgetExceeded,
    Identity,
    TransientInference,
    WarmstartError,
)
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore
from warmstart.web import create_app

QUESTION = "What is the standard shipping cost?"
PROFILE = "store_a_ch_standard"


def config(**changes):
    return replace(
        Config(
            environment="staging",
            allow_fixture_seeds=False,
            paid_inference=True,
            semantic_mode="off",
            generation_model="@cf/zai-org/glm-5.3-flash",
            embedding_model="@cf/baai/bge-small-en-v1.5",
            embedding_pooling="cls",
        ),
        **changes,
    )


def generation(policy):
    return {
        "response": json.dumps(
            {
                "answer": policy.facts["shipping:standard"],
                "fact_ids": [policy.source_ids["shipping:standard"]],
            }
        ),
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }


class Binding:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def run(self, model, inputs, options):
        self.calls.append((model, inputs, options))
        if self.fail:
            raise OSError("gateway unavailable")
        return {"data": [[1.0] * 384]} if "text" in inputs else generation(policies()[0])


def adapter(binding, settings=None, settings_config=None):
    return WorkersAIInference(
        binding,
        settings_config or config(),
        lambda value: value,
        settings or GatewaySettings("warmstart-staging"),
    )


async def test_both_model_calls_use_explicit_gateway_privacy_cache_and_single_attempt_options():
    binding = Binding()
    inference = adapter(binding)
    await inference.embed(QUESTION)
    await inference.generate(QUESTION, policies()[0], classify(QUESTION))
    assert len(binding.calls) == 2
    assert [call[0] for call in binding.calls] == [
        "@cf/baai/bge-small-en-v1.5",
        "@cf/zai-org/glm-5.3-flash",
    ]
    for _, _, options in binding.calls:
        assert options["gateway"] == {
            "id": "warmstart-staging",
            "skipCache": True,
            "collectLog": True,
            "retries": {"maxAttempts": 1},
        }
        assert options["extraHeaders"]["cf-aig-max-attempts"] == "1"
        assert options["extraHeaders"]["cf-aig-collect-log-payload"] == "false"
        assert "metadata" not in options["gateway"]
        assert QUESTION not in json.dumps(options)
        assert "cf-aig-collect-log" not in options["extraHeaders"]
    assert "x-session-affinity" not in binding.calls[0][2]["extraHeaders"]
    assert binding.calls[1][2]["extraHeaders"]["x-session-affinity"] == (
        config().signature(PROFILE, "v1")
    )
    assert binding.calls[1][1]["reasoning_effort"] == "low"
    assert binding.calls[1][1]["temperature"] == 0
    assert binding.calls[1][1]["max_completion_tokens"] == 512


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "default",
        "Default",
        "with spaces",
        "https://gateway.example/id",
        "../other",
        "a" * 65,
        "-name",
        "name-",
        "méta",
    ],
)
async def test_invalid_or_missing_gateway_never_calls_binding(identifier):
    binding = Binding()
    inference = adapter(binding, GatewaySettings(identifier))
    with pytest.raises(WarmstartError) as error:
        await inference.embed(QUESTION)
    assert error.value.status_code == 503
    with pytest.raises(WarmstartError) as error:
        await inference.generate(QUESTION, policies()[0], classify(QUESTION))
    assert error.value.status_code == 503
    assert binding.calls == []


def test_gateway_transport_fingerprint_changes_without_changing_answer_compatibility():
    first = GatewaySettings("warmstart-staging")
    second = replace(first, gateway_id="warmstart-pilot", log_mode="off")
    assert first.signature() != second.signature()
    assert config().signature(PROFILE, "v1") == (
        replace(config(), paid_inference=False).signature(PROFILE, "v1")
    )
    assert second.options()["gateway"]["collectLog"] is False
    assert second.options()["extraHeaders"]["cf-aig-collect-log-payload"] == "false"


async def test_bad_transport_preflight_does_not_reserve_or_retry():
    store, coordinator, binding = SQLiteStore(), SQLiteCoordinator(), Binding()
    inference = adapter(binding, GatewaySettings())
    service = WarmstartService(store, coordinator, inference, config(semantic_mode="shadow"))
    try:
        with pytest.raises(WarmstartError) as error:
            await service.answer(
                Identity("tester", frozenset(PROFILES)), AnswerRequest(question=QUESTION)
            )
        assert error.value.status_code == 503
        assert binding.calls == []
        assert (
            coordinator.connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        )
    finally:
        store.close()
        coordinator.close()


@pytest.mark.parametrize("fault", ["missing_id", "invalid_logmode", "missing_binding"])
async def test_transport_faults_return_controlled_503_without_spending(fault):
    store, coordinator, binding = SQLiteStore(), SQLiteCoordinator(), Binding()
    settings = GatewaySettings("warmstart-staging")
    if fault == "missing_id":
        settings = GatewaySettings()
    elif fault == "invalid_logmode":
        settings = GatewaySettings("warmstart-staging", log_mode="invalid")
    inference = adapter(None if fault == "missing_binding" else binding, settings)
    service = WarmstartService(store, coordinator, inference, config())

    async def identity(request):
        return Identity("mobile-tester", frozenset(PROFILES))

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(service, identity)),
            base_url="http://localhost",
        ) as client:
            response = await client.post("/v1/answer", json={"question": QUESTION})
        assert response.status_code == 503
        assert response.json() == {"error": "service_unavailable"}
        assert binding.calls == []
        assert (
            coordinator.connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0
        )
    finally:
        store.close()
        coordinator.close()


@pytest.mark.parametrize(
    "change", ["missing_gateway", "different_gateway", "inference_off", "logs_off"]
)
async def test_cache_only_switches_preserve_exact_answers_without_new_paid_side_effects(change):
    store, coordinator, binding = SQLiteStore(), SQLiteCoordinator(), Binding()
    inference = adapter(binding)
    service = WarmstartService(store, coordinator, inference, config())
    identity = Identity("tester", frozenset(PROFILES))
    request = AnswerRequest(question=QUESTION)
    try:
        first = await service.answer(identity, request)
        assert first.cache_status == "generated"
        reserved_before = coordinator.connection.execute(
            "SELECT COUNT(*) FROM reservations"
        ).fetchone()[0]
        if change == "missing_gateway":
            inference.gateway = GatewaySettings()
        elif change == "different_gateway":
            inference.gateway = GatewaySettings("warmstart-different")
        elif change == "logs_off":
            inference.gateway = GatewaySettings("warmstart-staging", log_mode="off")
        else:
            service.config = replace(service.config, paid_inference=False)
            inference.config = service.config
        second = await service.answer(identity, request)
        assert second.cache_status == "exact" and second.answer == first.answer
        assert len(binding.calls) == 1
        assert (
            coordinator.connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
            == reserved_before
        )
        if change in ("missing_gateway", "inference_off"):
            expected = BudgetExceeded if change == "inference_off" else WarmstartError
            with pytest.raises(expected) as error:
                await service.answer(identity, AnswerRequest(question="What is the delivery fee?"))
            assert error.value.status_code == (429 if change == "inference_off" else 503)
            assert len(binding.calls) == 1
    finally:
        store.close()
        coordinator.close()


async def test_gateway_failure_has_only_application_retry_and_reserved_attempts():
    store, coordinator, binding = SQLiteStore(), SQLiteCoordinator(), Binding()
    binding.fail = True
    service = WarmstartService(store, coordinator, adapter(binding), config())
    try:
        with pytest.raises(TransientInference):
            await service.answer(
                Identity("tester", frozenset(PROFILES)), AnswerRequest(question=QUESTION)
            )
        assert len(binding.calls) == 2
        assert all(call[2]["gateway"]["retries"] == {"maxAttempts": 1} for call in binding.calls)
        rows = coordinator.connection.execute(
            "SELECT kind,reserved,settled FROM reservations"
        ).fetchall()
        assert [tuple(row) for row in rows] == [("generation", 10000, 0), ("generation", 10000, 0)]
    finally:
        store.close()
        coordinator.close()


async def test_embedding_error_cannot_bypass_gateway_or_generation_budget():
    store, binding = SQLiteStore(), Binding()
    coordinator = SQLiteCoordinator(budget_microusd=10099)
    binding.fail = True
    service = WarmstartService(
        store,
        coordinator,
        adapter(binding, settings_config=config(semantic_mode="shadow")),
        config(semantic_mode="shadow"),
    )
    try:
        with pytest.raises(BudgetExceeded):
            await service.answer(
                Identity("tester", frozenset(PROFILES)), AnswerRequest(question=QUESTION)
            )
        assert len(binding.calls) == 1 and "text" in binding.calls[0][1]
        assert [
            tuple(row)
            for row in coordinator.connection.execute(
                "SELECT kind,reserved,settled FROM reservations"
            )
        ] == [("embedding", 100, 0)]
    finally:
        store.close()
        coordinator.close()


def test_deployment_renderer_requires_named_gateway_and_propagates_nonsecret_settings():
    values = {
        "CF_ACCOUNT_ID": "a" * 32,
        "D1_DATABASE_ID": "a" * 8 + "-" + "b" * 27,
        "ACCESS_ISSUER": "https://example.cloudflareaccess.com",
        "ACCESS_AUDIENCE": "aud",
    }
    for identifier in (None, "", "default", "invalid name"):
        given = values if identifier is None else values | {"AI_GATEWAY_ID": identifier}
        with pytest.raises(ValueError):
            render("staging", given)
    rendered = render("staging", values | {"AI_GATEWAY_ID": "warmstart-staging"})
    assert rendered["vars"]["AI_GATEWAY_ID"] == "warmstart-staging"
    assert rendered["vars"]["AI_GATEWAY_LOG_MODE"] == "metadata"
    assert rendered["vars"]["PAID_INFERENCE"] == "false"
    assert (
        render(
            "staging", values | {"AI_GATEWAY_ID": "warmstart-staging", "AI_GATEWAY_LOG_MODE": "off"}
        )["vars"]["AI_GATEWAY_LOG_MODE"]
        == "off"
    )
    with pytest.raises(ValueError):
        render(
            "pilot", values | {"AI_GATEWAY_ID": "warmstart-pilot", "AI_GATEWAY_LOG_MODE": "full"}
        )
    validate_gateway_id("a")
    validate_gateway_id("warmstart-pilot")
