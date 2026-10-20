import base64
import hashlib
import json

import pytest

from warmstart.access import verify_access
from warmstart.models import Unauthorized


def encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


async def resolve(*, claims=None, header=None, valid=True, service=False):
    issuer = "https://example.cloudflareaccess.com"
    principal = "service:client.access" if service else "user:tester"
    key = hashlib.sha256(principal.encode()).hexdigest()
    payload = {"iss": issuer, "aud": ["audience"], "exp": 200, "sub": "tester"}
    if service:
        payload.update(sub="", common_name="client.access")
    payload.update(claims or {})
    token = ".".join(
        (encoded(header or {"alg": "RS256", "kid": "trusted"}), encoded(payload), "c2ln")
    )

    async def verify(actual_issuer, kid, signed, signature):
        assert actual_issuer == issuer and kid == "trusted" and signature == b"sig"
        return valid

    return await verify_access(
        token,
        issuer=issuer,
        audience="audience",
        now=100,
        memberships={key: {"profiles": ["store_a_ch_standard"], "owner": False}},
        verify_signature=verify,
    )


async def test_access_authorization_and_service_namespace():
    user = await resolve()
    service = await resolve(service=True)
    assert user.subject != service.subject and not user.owner
    assert user.allowed_profiles == frozenset({"store_a_ch_standard"})


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://evil.example"},
        {"aud": ["other"]},
        {"aud": {"audience": True}},
        {"exp": 100},
        {"exp": float("nan")},
        {"nbf": "yesterday"},
        {"nbf": 101},
        {"sub": "uninvited"},
        {"sub": None},
    ],
)
async def test_invalid_claims_fail_closed(claims):
    with pytest.raises(Unauthorized):
        await resolve(claims=claims)


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none", "kid": "trusted"},
        {"alg": "HS256", "kid": "trusted"},
        {"alg": "RS256", "kid": "trusted", "jku": "https://evil.example/keys"},
    ],
)
async def test_untrusted_signature_selection(header):
    with pytest.raises(Unauthorized):
        await resolve(header=header)


async def test_signature_failure():
    with pytest.raises(Unauthorized):
        await resolve(valid=False)
