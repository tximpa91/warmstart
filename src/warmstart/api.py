"""Local-only bootstrap. Workers import warmstart.web, never this module."""

import os
from ipaddress import ip_address
from pathlib import Path

from fastapi import Request
from fastapi.staticfiles import StaticFiles

from warmstart.config import Config
from warmstart.core import WarmstartService
from warmstart.data import PROFILES
from warmstart.inference import OfflineInference
from warmstart.models import Identity, Unauthorized
from warmstart.sqlite import SQLiteCoordinator, SQLiteStore
from warmstart.web import create_app


async def local_identity(request: Request) -> Identity:
    """Fixed owner identity on loopback only. Identity headers are never trusted."""
    if request.client is None:
        raise Unauthorized()
    try:
        loopback = ip_address(request.client.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback or request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise Unauthorized()
    return Identity("local-demo-owner", frozenset(PROFILES), owner=True)


def local_service() -> WarmstartService:
    path = os.environ.get("WARMSTART_LOCAL_DB", "artifacts/warmstart.sqlite3")
    return WarmstartService(
        SQLiteStore(path), SQLiteCoordinator(path), OfflineInference(), Config()
    )


app = create_app(local_service(), local_identity)
app.mount(
    "/console", StaticFiles(directory=Path(__file__).resolve().parents[2] / "public", html=True)
)
