"""End-to-end tests for POST /auth/forgot-password and POST /auth/reset-password — see
app/services/password_reset_service.py and app/api/v1/auth.py.
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
    from app.api.deps import (
        get_arq_redis,
        get_db,
        get_password_reset_account_limiter,
        get_password_reset_ip_limiter,
        get_settings_dep,
    )
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=False)
    # The real password-reset limiters are process-wide module-level singletons (capacity=3),
    # shared across every test in the session — generous test-only instances here, same as
    # test_auth_rate_limiting.py already does for login, so tests in this file calling
    # /auth/forgot-password more than 3 times total don't trip each other's rate limit.
    app.dependency_overrides[get_password_reset_ip_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    app.dependency_overrides[get_password_reset_account_limiter] = lambda: RateLimiter(
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
    assert match, f"no reset token found in sent email: {payload['html']!r}"
    return match.group(1)


@pytest.mark.asyncio
async def test_forgot_password_sends_a_working_reset_link(
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

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-reset-flow",
            "email": "reset-flow@example.com",
            "name": "Founder",
            "password": "original-password-123",
        },
    )

    r = await api_client.post(
        "/api/v1/auth/forgot-password", json={"email": "reset-flow@example.com"}
    )
    assert r.status_code == 204
    assert len(sent) == 1
    token = _extract_token(sent[0])

    reset = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-password-456"},
    )
    assert reset.status_code == 200

    # Old password no longer works, new one does.
    old = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "reset-flow@example.com", "password": "original-password-123"},
    )
    assert old.status_code == 401

    new = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "reset-flow@example.com", "password": "brand-new-password-456"},
    )
    assert new.status_code == 200


@pytest.mark.asyncio
async def test_forgot_password_for_unknown_email_still_returns_204_and_sends_nothing(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    r = await api_client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody-here@example.com"}
    )
    assert r.status_code == 204
    assert sent == []  # never even attempted — same response either way, no enumeration


@pytest.mark.asyncio
async def test_reset_password_with_garbage_token_fails(api_client: AsyncClient) -> None:
    r = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "whatever-password-123"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "authentication_error"


@pytest.mark.asyncio
async def test_reset_password_token_is_single_use(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-single-use",
            "email": "single-use@example.com",
            "name": "Founder",
            "password": "original-password-123",
        },
    )
    await api_client.post("/api/v1/auth/forgot-password", json={"email": "single-use@example.com"})
    token = _extract_token(sent[0])

    first = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-password-456"},
    )
    assert first.status_code == 200

    second = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "yet-another-password-789"},
    )
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_reset_password_expired_token_fails(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app
    from app.models.password_reset import PasswordResetToken

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-expired",
            "email": "expired-token@example.com",
            "name": "Founder",
            "password": "original-password-123",
        },
    )
    await api_client.post(
        "/api/v1/auth/forgot-password", json={"email": "expired-token@example.com"}
    )
    token = _extract_token(sent[0])

    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.api_keys import hash_api_key

    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_api_key(token))
    )
    record = result.scalar_one()
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()

    r = await api_client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-password-456"},
    )
    assert r.status_code == 401


def _make_rate_limited_client_fixture(*, ip_capacity: int, account_capacity: int):
    @pytest_asyncio.fixture
    async def _fixture(db_session, _migrated_db):
        from app.api.deps import (
            get_arq_redis,
            get_db,
            get_password_reset_account_limiter,
            get_password_reset_ip_limiter,
            get_settings_dep,
        )
        from app.main import app

        ip_limiter = RateLimiter(capacity=ip_capacity, refill_rate=0.0001)
        account_limiter = RateLimiter(capacity=account_capacity, refill_rate=0.0001)

        async def override_get_db():
            yield db_session

        async def override_get_arq_redis():
            return _FakeArqRedis()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_arq_redis] = override_get_arq_redis
        app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=False)
        app.dependency_overrides[get_password_reset_ip_limiter] = lambda: ip_limiter
        app.dependency_overrides[get_password_reset_account_limiter] = lambda: account_limiter
        try:
            async with app.router.lifespan_context(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    yield client
        finally:
            app.dependency_overrides.clear()

    return _fixture


api_client_tiny_account_limit = _make_rate_limited_client_fixture(
    ip_capacity=1000, account_capacity=2
)


@pytest.mark.asyncio
async def test_forgot_password_returns_429_once_the_per_account_limit_is_exhausted(
    api_client_tiny_account_limit: AsyncClient,
) -> None:
    target_email = "rate-limited@example.com"
    for _ in range(2):  # account_capacity=2
        r = await api_client_tiny_account_limit.post(
            "/api/v1/auth/forgot-password", json={"email": target_email}
        )
        assert r.status_code == 204

    r = await api_client_tiny_account_limit.post(
        "/api/v1/auth/forgot-password", json={"email": target_email}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_requests"
