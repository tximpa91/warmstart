"""Portable API factory. Importing this module never creates a local database."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from warmstart.core import WarmstartService
from warmstart.models import (
    AnswerRequest,
    AnswerResponse,
    Identity,
    InvalidationRequest,
    Unauthorized,
    WarmstartError,
)

IdentityResolver = Callable[[Request], Awaitable[Identity]]
logger = logging.getLogger("warmstart")


def create_app(service: WarmstartService, identity_resolver: IdentityResolver) -> FastAPI:
    app = FastAPI(
        title="Warmstart",
        version="0.1.0",
        description="Synthetic support caching pilot; policies are fictional.",
        docs_url="/docs" if service.config.environment == "local" else None,
        redoc_url=None,
    )
    app.state.service = service

    @app.exception_handler(WarmstartError)
    async def controlled_error(request: Request, exc: WarmstartError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Type only: provider exceptions can carry sensitive request data.
        logger.error("request_failed type=%s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"error": "service_unavailable"})

    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "warmstart"}

    @app.post("/v1/answer", response_model=AnswerResponse)
    async def answer(body: AnswerRequest, request: Request) -> AnswerResponse:
        identity = await identity_resolver(request)
        return await service.answer(identity, body)

    @app.get("/v1/metrics")
    async def metrics(request: Request) -> dict[str, object]:
        return await service.metrics(await identity_resolver(request))

    @app.post("/v1/admin/invalidate")
    async def invalidate(body: InvalidationRequest, request: Request) -> dict[str, str]:
        await service.invalidate(await identity_resolver(request), body.policy_version)
        return {"policy_version": body.policy_version}

    @app.get("/")
    async def root(request: Request) -> dict[str, object]:
        identity = await identity_resolver(request)
        if not identity.allowed_profiles:
            raise Unauthorized()
        return {
            "service": "Warmstart",
            "data": "original agent-authored fictional fixtures; human approval pending",
            "semantic_mode": service.config.semantic_mode,
            "paid_inference": service.config.paid_inference,
            "profiles": sorted(identity.allowed_profiles),
            "usage": "POST /v1/answer with question and authorized profile",
        }

    return app
