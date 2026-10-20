"""Verify Access claims using an injected signature verifier, never client identity headers."""

import base64
import hashlib
import json
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

from warmstart.models import Identity, Unauthorized


def decode_part(value: str) -> dict[str, Any]:
    parsed = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JWT object")
    return parsed


async def verify_access(
    token: str,
    *,
    issuer: str,
    audience: str,
    memberships: dict[str, dict[str, Any]],
    verify_signature: Callable[[str, str, bytes, bytes], Awaitable[bool]],
    now: float | None = None,
) -> Identity:
    try:
        if not issuer.startswith("https://") or not audience or len(token) > 16000:
            raise ValueError("Missing Access configuration")
        header_part, claims_part, signature_part = token.split(".")
        header, claims = decode_part(header_part), decode_part(claims_part)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("Unsupported signature")
        if header.get("crit") or header.get("jku") or header.get("jwk"):
            raise ValueError("Untrusted key selection")
        instant = time.time() if now is None else now
        exp = claims.get("exp")
        if (
            not isinstance(exp, (int, float))
            or isinstance(exp, bool)
            or not math.isfinite(exp)
            or exp <= instant
        ):
            raise ValueError("Expired token")
        if "nbf" in claims:
            nbf = claims["nbf"]
            if type(nbf) not in (int, float) or not math.isfinite(nbf) or nbf > instant:
                raise ValueError("Invalid token validity")
        if claims.get("iss", "").rstrip("/") != issuer.rstrip("/"):
            raise ValueError("Incorrect issuer")
        audiences = claims.get("aud", [])
        if isinstance(audiences, str):
            audiences = [audiences]
        if not isinstance(audiences, list) or audience not in audiences:
            raise ValueError("Incorrect audience")
        signed = f"{header_part}.{claims_part}".encode()
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        if not await verify_signature(issuer, header["kid"], signed, signature):
            raise ValueError("Invalid signature")
        # Explicit namespaces prevent a service token from colliding with a user ID.
        subject = claims.get("sub")
        service = claims.get("common_name")
        if isinstance(subject, str) and subject:
            principal = "user:" + subject
        elif subject == "" and isinstance(service, str) and service:
            principal = "service:" + service
        else:
            raise ValueError("Missing subject")
        subject_hash = hashlib.sha256(principal.encode()).hexdigest()
        member = memberships.get(subject_hash)
        if not member or not isinstance(member.get("profiles"), list):
            raise ValueError("No authorized profile")
        if not all(isinstance(profile, str) for profile in member["profiles"]):
            raise ValueError("Invalid profile membership")
        return Identity(subject_hash, frozenset(member["profiles"]), member.get("owner") is True)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise Unauthorized("Access token or membership is invalid") from exc
