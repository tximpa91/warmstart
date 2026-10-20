"""Local-only binding check entrypoint. Never used by the staging/pilot configuration."""

from typing import Any

from starlette.responses import JSONResponse
from workers import asgi

from warmstart.cloud import D1Store, DOCoordinator
from worker import PilotCoordinator, application, convert  # noqa: F401 (Durable Object export)


async def smoke(scope: dict[str, Any], receive: Any, send: Any) -> None:
    if scope.get("path") != "/__bindings":
        await application(scope, receive, send)
        return
    env = scope["env"]
    if str(getattr(env, "SMOKE_LOCAL", "")) != "true":
        await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
        return
    store = D1Store(env.DB)
    coordinator = DOCoordinator(env.COORDINATOR, convert)
    policy = await store.policy("store_a_ch_standard", "v1")
    admission = await coordinator.admit("local-binding-check", 1700000000)
    reservation = await coordinator.reserve("embedding", 1, 1700000000)
    await coordinator.settle(reservation, 0)
    await JSONResponse(
        {
            "d1_policy": policy.version if policy else None,
            "admission": admission.version,
            "reserved_and_settled": True,
        }
    )(scope, receive, send)


Default = asgi.entrypoint(smoke)
