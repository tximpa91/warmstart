import asyncio
import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from seed_sql import seed_sql

from warmstart.cloud import D1Store, DOCoordinator, WorkersAIInference
from warmstart.config import Config
from warmstart.data import policies
from warmstart.gateway import GatewaySettings
from warmstart.guards import classify
from warmstart.ledger import BindingLedger
from warmstart.models import (
    BudgetExceeded,
    CachedAnswer,
    InvalidInference,
    QuotaExceeded,
    RequestEvent,
)


class Statement:
    def __init__(self, connection, sql):
        self.connection, self.sql, self.params = connection, sql, ()

    def bind(self, *values):
        self.params = values
        return self

    async def all(self):
        return {"results": [dict(row) for row in self.connection.execute(self.sql, self.params)]}

    async def run(self):
        self.connection.execute(self.sql, self.params)


class D1:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(Path("migrations/0001_initial.sql").read_text() + seed_sql())

    def prepare(self, sql):
        return Statement(self.connection, sql)


async def test_d1_contract_and_immutable_policy():
    binding = D1()
    store = D1Store(binding)
    policy = policies()[0]
    assert await store.policy(policy.profile, policy.version) == policy
    candidates = await store.candidates(policy.profile, policy.version)
    assert len(candidates) == 5 and not any(item.human_approved for item in candidates)
    assert await store.exact_get("absent", 0) is None
    entry = CachedAnswer("key", "answer", ("ref",), "v1", 20, "signature")
    await store.exact_put(entry)
    assert await store.exact_get("key", 19) == entry
    assert await store.exact_get("key", 20) is None
    await store.event(
        RequestEvent("request", "hash", policy.profile, "v1", "exact", 2, 0, 0, 0, 0, False)
    )
    assert (await store.metrics())["by_status"] == {"exact": 1}
    # Re-seeding is safe; changing or deleting an admitted edition is not.
    binding.connection.executescript(seed_sql())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        binding.connection.execute("UPDATE policies SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        binding.connection.execute("DELETE FROM policies")
    binding.connection.close()


class KV:
    def __init__(self):
        self.data = {}
        self.fail = False

    async def get(self, key):
        await asyncio.sleep(0)
        return self.data.get(key)

    async def put(self, values):
        await asyncio.sleep(0)
        if self.fail:
            raise OSError("atomic put failed")
        self.data.update(values)


def ledger(storage, **kwargs):
    return BindingLedger(storage, lambda value: value, **kwargs)


async def test_durable_budget_concurrency_restart_and_unknown_outcomes():
    storage = KV()
    coordinator = ledger(storage, budget_microusd=100)
    now = time.time()
    results = await asyncio.gather(
        *(
            coordinator.operation("reserve", {"kind": "generation", "amount": 60, "now": now})
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(item, BudgetExceeded) for item in results) == 1
    reservation = next(item["reservation_id"] for item in results if isinstance(item, dict))
    restarted = ledger(storage, budget_microusd=100)
    assert (await restarted.operation("state", {"now": now}))["committed_microusd"] == 60
    await restarted.operation("settle", {"reservation_id": reservation, "actual": 30})
    await restarted.operation("settle", {"reservation_id": reservation, "actual": 30})
    with pytest.raises(ValueError):
        await restarted.operation("settle", {"reservation_id": reservation, "actual": 0})
    assert (await restarted.operation("state", {"now": now}))["committed_microusd"] == 30


async def test_durable_atomic_failure_does_not_create_free_reservation():
    storage = KV()
    coordinator = ledger(storage)
    storage.fail = True
    with pytest.raises(OSError):
        await coordinator.operation("reserve", {"kind": "generation", "amount": 10})
    assert storage.data == {}


async def test_durable_quota_policy_and_fenced_leases():
    storage = KV()
    coordinator = ledger(storage, identity_limit=1, max_concurrency=1)
    now = time.time()
    first = await coordinator.operation("admit", {"identity_id": "x", "now": now})
    assert first["version"] == "v1"
    with pytest.raises(QuotaExceeded):
        await coordinator.operation("admit", {"identity_id": "x", "now": now})
    await coordinator.operation("activate", {"version": "v2"})
    assert (await coordinator.operation("admit", {"identity_id": "y", "now": now}))[
        "version"
    ] == "v2"
    old = await coordinator.operation("acquire", {"key": "a", "ttl": 1, "now": now})
    assert not (await coordinator.operation("acquire", {"key": "b", "ttl": 1, "now": now}))["token"]
    new = await coordinator.operation("acquire", {"key": "a", "ttl": 10, "now": now + 2})
    await coordinator.operation("release", {"key": "a", "token": old["token"], "now": now + 2})
    assert (
        new["token"]
        and not (await coordinator.operation("acquire", {"key": "a", "ttl": 10, "now": now + 2}))[
            "token"
        ]
    )


class Provider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def run(self, *args):
        self.calls.append(args)
        return self.response


def live_config():
    return Config(
        environment="staging",
        allow_fixture_seeds=False,
        paid_inference=True,
        generation_model="@cf/zai-org/glm-5.3-flash",
        embedding_model="@cf/baai/bge-small-en-v1.5",
        embedding_pooling="cls",
    )


async def test_workers_ai_usage_prefix_and_schema_contract():
    policy = policies()[0]
    provider = Provider(
        {
            "response": json.dumps(
                {
                    "answer": policy.facts["shipping:standard"],
                    "fact_ids": [policy.source_ids["shipping:standard"]],
                }
            ),
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
        }
    )
    inference = WorkersAIInference(
        provider, live_config(), lambda value: value, GatewaySettings("warmstart-staging")
    )
    result = await inference.generate(
        "What is the shipping cost?", policy, classify("What is the shipping cost?")
    )
    assert result.usage.cost_microusd == 104  # 200*.15 + 800*.03 + 100*.50
    assert result.usage.cached_input_tokens == 800
    assert provider.calls[0][1]["reasoning_effort"] == "low"
    assert "x-session-affinity" in provider.calls[0][2]["extraHeaders"]
    provider.response["usage"]["prompt_tokens"] = -1
    with pytest.raises(InvalidInference):
        await inference.generate("question", policy, classify("What is the shipping cost?"))


async def test_embedding_estimate_fingerprint_and_truncation_bound():
    provider = Provider({"data": [[1.0] * 384]})
    config = live_config()
    inference = WorkersAIInference(
        provider, config, lambda value: value, GatewaySettings("warmstart-staging")
    )
    result = await inference.embed("shipping cost")
    assert result.usage.estimated and result.usage.cost_microusd > 0
    assert (
        config.embedding_fingerprint()
        != replace(config, embedding_pooling="mean").embedding_fingerprint()
    )
    with pytest.raises(InvalidInference):
        await inference.embed("a" * 481)
    assert len(provider.calls) == 1


async def test_do_rpc_contract():
    from types import SimpleNamespace

    storage = KV()
    implementation = ledger(storage)

    class Stub:
        async def fetch(self, url, *, method, headers, body):
            assert method == "POST" and headers["Content-Type"] == "application/json"
            result = await implementation.operation(url.rsplit("/", 1)[1], json.loads(body))

            async def text():
                return json.dumps(result)

            return SimpleNamespace(status=200, text=text)

    client = DOCoordinator(SimpleNamespace(getByName=lambda _: Stub()), lambda value: value)
    admission = await client.admit(hashlib.sha256(b"subject").hexdigest(), time.time())
    assert admission.version == "v1"
    reservation = await client.reserve("embedding", 50, time.time())
    await client.settle(reservation, 10)
    assert (await client.state())["committed_microusd"] == 10
