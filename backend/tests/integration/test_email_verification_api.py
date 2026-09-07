"""End-to-end tests for email verification: POST /auth/register no longer grants a session by
itself, and POST /auth/verify-email is what actually grants one. See
app/services/email_verification_service.py and app/api/v1/auth.py.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.rate_limit import RateLimiter

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    async def ping(self) -> bool:
        return True


def _settings(*, with_resend: bool = False) -> Settings:
    kwargs: dict[str, object] = dict(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        frontend_origin="https://app.test",
    )
    if with_resend:
        kwargs["resend_api_key"] = "re_test_key"
        kwargs["resend_from_email"] = "Threadly <notifications@usethreadly.co>"
    return Settings(**kwargs)


def _patch_resend(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import app.core.email.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db, get_register_ip_limiter, get_settings_dep
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=False)
    app.dependency_overrides[get_register_ip_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


def _extract_token(sent_request: httpx.Request) -> str:
    payload = json.loads(sent_request.content)
    match = re.search(r"token=([\w-]+)", payload["html"])
    assert match, f"no verification token found in sent email: {payload['html']!r}"
    return match.group(1)


async def _register(api_client: AsyncClient, *, email: str = "new-signup@example.com") -> None:
    r = await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": f"acme-{email.split('@')[0]}",
            "email": email,
            "name": "Founder",
            "password": "original-password-123",
        },
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_register_does_not_grant_a_session(api_client: AsyncClient) -> None:
    await _register(api_client)
    # No session cookie means every authenticated route rejects the same client that just
    # registered — /auth/me is a convenient, always-present probe for "is there a session."
    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_login_before_verification_fails(api_client: AsyncClient) -> None:
    await _register(api_client, email="unverified@example.com")
    r = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "unverified@example.com", "password": "original-password-123"},
    )
    assert r.status_code == 401
    assert "verify your email" in r.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_register_sends_a_working_verification_link(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"id": "email_123"})

    _patch_resend(monkeypatch, handler)

    await _register(api_client, email="verify-flow@example.com")
    assert len(sent) == 1
    token = _extract_token(sent[0])

    verify = await api_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200
    assert verify.json()["email"] == "verify-flow@example.com"

    # Verifying grants a session immediately — no second login trip required.
    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 200

    # Login also works now, independently of the session verify already granted.
    fresh_client_login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "verify-flow@example.com", "password": "original-password-123"},
    )
    assert fresh_client_login.status_code == 200


@pytest.mark.asyncio
async def test_verify_email_with_garbage_token_fails(api_client: AsyncClient) -> None:
    r = await api_client.post(
        "/api/v1/auth/verify-email", json={"token": "not-a-real-token"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "authentication_error"


@pytest.mark.asyncio
async def test_verify_email_token_is_single_use(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    await _register(api_client, email="single-use-verify@example.com")
    token = _extract_token(sent[0])

    first = await api_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200

    second = await api_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_verify_email_expired_token_fails(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app
    from app.models.email_verification import EmailVerificationToken

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    await _register(api_client, email="expired-verify@example.com")
    token = _extract_token(sent[0])

    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.api_keys import hash_api_key

    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == hash_api_key(token)
        )
    )
    record = result.scalar_one()
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()

    r = await api_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 401
