"""Actual Python Worker entrypoint. Platform-only imports stay here."""

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import Request as APIRequest
from js import Object, Uint8Array, crypto
from pyodide.ffi import to_js as py_to_js
from workers import DurableObject, Response, asgi, fetch

from warmstart.access import verify_access
from warmstart.cloud import D1Store, DOCoordinator, WorkersAIInference
from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.gateway import GatewaySettings
from warmstart.ledger import BindingLedger
from warmstart.models import Identity, WarmstartError
from warmstart.web import create_app

_key_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_key_lock = asyncio.Lock()


def convert(value: object) -> Any:
    return py_to_js(value, dict_converter=Object.fromEntries)


async def check_signature(issuer: str, kid: str, signed: bytes, signature: bytes) -> bool:
    # The issuer is trusted server configuration; JWT headers cannot choose key URLs.
    async with _key_lock:
        cached = _key_cache.get(issuer)
        if cached is None or cached[0] < time.time():
            async with asyncio.timeout(2):
                response = await fetch(issuer.rstrip("/") + "/cdn-cgi/access/certs")
                if response.status != 200:
                    return False
                document = json.loads(await response.text())
            # Unknown key IDs cannot repeatedly force refreshes during this short TTL.
            cached = (time.time() + 60, document["keys"])
            _key_cache[issuer] = cached
    key = next((item for item in cached[1] if item.get("kid") == kid), None)
    if key is None or key.get("kty") != "RSA":
        return False
    algorithm = {"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"}
    imported = await crypto.subtle.importKey(
        "jwk",
        convert(key),
        convert(algorithm),
        False,
        convert(["verify"]),
    )
    valid = await crypto.subtle.verify(
        "RSASSA-PKCS1-v1_5",
        imported,
        Uint8Array.new(convert(list(signature))),
        Uint8Array.new(convert(list(signed))),
    )
    return bool(valid)


class PilotCoordinator(DurableObject):
    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self.ledger = BindingLedger(
            ctx.storage,
            convert,
            budget_microusd=int(getattr(env, "MONTHLY_BUDGET_MICROUSD", "12000000")),
        )

    async def fetch(self, request: Any) -> Any:
        try:
            operation = urlparse(request.url).path.strip("/")
            payload = json.loads(await request.text())
            result = await self.ledger.operation(operation, payload)
            return Response.json(result)
        except WarmstartError as exc:
            return Response.json({"error": exc.code}, status=exc.status_code)
        except Exception:
            return Response.json({"error": "coordination_failed"}, status=503)


# A small ASGI dispatcher builds the configured service from this request's bindings.
# No SQLite bootstrap, local identity, or offline inference is imported by this path.
_apps: dict[str, Any] = {}


async def application(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    env = scope["env"]
    environment = str(getattr(env, "APP_ENV", "staging"))
    # This map is an isolate-local optimization, not authorization state.
    key = environment
    if key not in _apps:
        config = Config(
            environment=environment,
            allow_fixture_seeds=False,
            semantic_mode=str(getattr(env, "SEMANTIC_MODE", "off")),
            paid_inference=str(getattr(env, "PAID_INFERENCE", "false")) == "true",
            generation_model="@cf/zai-org/glm-5.3-flash",
            embedding_model="@cf/baai/bge-small-en-v1.5",
            embedding_pooling="cls",
            semantic_threshold=float(getattr(env, "SEMANTIC_THRESHOLD", "1.0")),
        )
        service = WarmstartService(
            D1Store(env.DB),
            DOCoordinator(env.COORDINATOR, convert),
            WorkersAIInference(
                getattr(env, "AI", None),
                config,
                convert,
                GatewaySettings(
                    gateway_id=str(getattr(env, "AI_GATEWAY_ID", "")),
                    log_mode=str(getattr(env, "AI_GATEWAY_LOG_MODE", "metadata")),
                ),
            ),
            config,
        )

        async def identity(request: APIRequest) -> Identity:
            return await verify_access(
                request.headers.get("Cf-Access-Jwt-Assertion", ""),
                issuer=str(getattr(env, "ACCESS_ISSUER", "")),
                audience=str(getattr(env, "ACCESS_AUDIENCE", "")),
                memberships=json.loads(str(getattr(env, "MEMBERSHIPS_JSON", "{}"))),
                verify_signature=check_signature,
                now=time.time(),
            )

        _apps[key] = create_app(service, identity)
    await _apps[key](scope, receive, send)


Default = asgi.entrypoint(application)
