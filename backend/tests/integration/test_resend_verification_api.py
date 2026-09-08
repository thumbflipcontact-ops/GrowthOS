"""End-to-end tests for POST /auth/resend-verification — see
app/services/email_verification_service.py's resend() and app/api/v1/auth.py.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

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


def _extract_token(sent_request: httpx.Request) -> str:
    payload = json.loads(sent_request.content)
    match = re.search(r"token=([\w-]+)", payload["html"])
    assert match, f"no verification token found in sent email: {payload['html']!r}"
    return match.group(1)


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import (
        get_arq_redis,
        get_db,
        get_resend_verification_account_limiter,
        get_resend_verification_ip_limiter,
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
    # The real resend-verification limiters are process-wide module-level singletons
    # (capacity=3), shared across every test in the session — generous test-only instances
    # here, same as test_password_reset_api.py does for its own limiters.
    app.dependency_overrides[get_resend_verification_ip_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    app.dependency_overrides[get_resend_verification_account_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resend_verification_sends_a_new_working_link(
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
            "org_slug": "acme-resend-flow",
            "email": "resend-flow@example.com",
            "name": "Founder",
            "password": "original-password-123",
        },
    )

    r = await api_client.post(
        "/api/v1/auth/resend-verification", json={"email": "resend-flow@example.com"}
    )
    assert r.status_code == 204
    # sent[0] is /auth/register's own verification email — resend sends a second, independent
    # one rather than reusing/extending it.
    assert len(sent) == 2

    token = _extract_token(sent[-1])
    verify = await api_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200
    assert verify.json()["email"] == "resend-flow@example.com"


@pytest.mark.asyncio
async def test_resend_verification_for_unknown_email_still_returns_204_and_sends_nothing(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    r = await api_client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody-here@example.com"}
    )
    assert r.status_code == 204
    assert sent == []  # never even attempted — same response either way, no enumeration


@pytest.mark.asyncio
async def test_resend_verification_for_an_already_verified_email_sends_nothing(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:
    from app.api.deps import get_settings_dep
    from app.main import app
    from app.repositories.user_repository import UserRepository

    app.dependency_overrides[get_settings_dep] = lambda: _settings(with_resend=True)

    sent: list[httpx.Request] = []
    _patch_resend(monkeypatch, lambda request: (sent.append(request), httpx.Response(200))[1])

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-already-verified",
            "email": "already-verified@example.com",
            "name": "Founder",
            "password": "original-password-123",
        },
    )
    sent.clear()  # discard registration's own verification email — irrelevant to this test

    user = await UserRepository(db_session).get_by_email("already-verified@example.com")
    assert user is not None
    user.email_verified_at = datetime.now(UTC)
    await db_session.flush()

    r = await api_client.post(
        "/api/v1/auth/resend-verification", json={"email": "already-verified@example.com"}
    )
    assert r.status_code == 204
    assert sent == []  # already verified — same response, but nothing was sent


def _make_rate_limited_client_fixture(*, ip_capacity: int, account_capacity: int):
    @pytest_asyncio.fixture
    async def _fixture(db_session, _migrated_db):
        from app.api.deps import (
            get_arq_redis,
            get_db,
            get_resend_verification_account_limiter,
            get_resend_verification_ip_limiter,
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
        app.dependency_overrides[get_resend_verification_ip_limiter] = lambda: ip_limiter
        app.dependency_overrides[get_resend_verification_account_limiter] = lambda: account_limiter
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
async def test_resend_verification_returns_429_once_the_per_account_limit_is_exhausted(
    api_client_tiny_account_limit: AsyncClient,
) -> None:
    target_email = "rate-limited-resend@example.com"
    for _ in range(2):  # account_capacity=2
        r = await api_client_tiny_account_limit.post(
            "/api/v1/auth/resend-verification", json={"email": target_email}
        )
        assert r.status_code == 204

    r = await api_client_tiny_account_limit.post(
        "/api/v1/auth/resend-verification", json={"email": target_email}
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_requests"
