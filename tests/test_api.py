import subprocess
import sys

import httpx
import pytest

from warmstart.core import WarmstartService
from warmstart.data import PROFILES
from warmstart.inference import OfflineInference
from warmstart.models import Identity
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore
from warmstart.web import create_app


@pytest.fixture
async def client():
    store, coordinator = SQLiteStore(), SQLiteCoordinator()
    service = WarmstartService(store, coordinator, OfflineInference())

    async def verified_identity(request):
        # Test resolver ignores attacker-supplied identities and grants only Shop A.
        return Identity("verified", frozenset({"store_a_ch_standard"}))

    app = create_app(service, verified_identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as http_client:
        yield http_client
    store.close()
    coordinator.close()


async def test_health_and_validated_answer(client):
    assert (await client.get("/healthz")).json()["status"] == "ok"
    result = await client.post("/v1/answer", json={"question": "What is the shipping cost?"})
    assert result.status_code == 200
    assert "CHF 5" in result.json()["answer"]
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-content-type-options"] == "nosniff"


async def test_input_and_authorization(client):
    result = await client.post("/v1/answer", json={"question": "x"})
    assert result.status_code == 422
    result = await client.post(
        "/v1/answer", json={"question": "What is shipping cost?", "subject": "owner"}
    )
    assert result.status_code == 422
    result = await client.post(
        "/v1/answer",
        json={"question": "What is shipping cost?", "profile": "store_b_ch_standard"},
        headers={"x-tenant": "store_b", "x-user-role": "owner"},
    )
    assert result.status_code == 403
    assert (await client.get("/v1/metrics")).status_code == 403
    assert (
        await client.post("/v1/admin/invalidate", json={"policy_version": "v2"})
    ).status_code == 403


def test_portable_import_does_not_load_sqlite():
    result = subprocess.run(
        [sys.executable, "-c", "import warmstart.web,sys; assert 'sqlite3' not in sys.modules"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_default_local_identity_rejects_nonlocal_and_spoofed_host():
    from starlette.requests import Request

    from warmstart.api import local_identity
    from warmstart.models import Unauthorized

    for client_address, host in (("203.0.113.1", "localhost"), ("127.0.0.1", "evil.example")):
        request = Request(
            {
                "type": "http",
                "scheme": "http",
                "path": "/",
                "query_string": b"",
                "headers": [(b"host", host.encode())],
                "client": (client_address, 1000),
                "server": (host, 80),
            }
        )
        with pytest.raises(Unauthorized):
            await local_identity(request)
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "headers": [(b"host", b"localhost")],
            "client": ("127.0.0.1", 1000),
            "server": ("localhost", 80),
        }
    )
    identity = await local_identity(request)
    assert identity.owner and identity.allowed_profiles == frozenset(PROFILES)
