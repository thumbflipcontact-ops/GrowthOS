"""End-to-end tests for GET /auth/google/start and /auth/google/callback — see
app/api/v1/auth_oauth.py and app/services/google_oauth_service.py.
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.core.security import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

pytestmark = pytest.mark.integration

_TOKEN_RESPONSE = {
    "access_token": "at-1",
    "token_type": "bearer",
    "expires_in": 3600,
    "scope": "openid email profile",
}


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        frontend_origin="https://app.test",
        oauth_frontend_redirect_url="https://app.test/dashboard",
        google_oauth_client_id="gcid",
        google_oauth_client_secret="gcsecret",
    )


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_db, get_google_oauth_ip_limiter, get_settings_dep
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings_dep] = lambda: _settings()
    # Same generous-test-limiter override every rate-limited auth endpoint's own test file
    # uses — the real instance is a process-wide singleton shared across the whole session.
    app.dependency_overrides[get_google_oauth_ip_limiter] = lambda: RateLimiter(
        capacity=1000, refill_rate=1000
    )
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test", follow_redirects=False
            ) as client:
                yield client
    finally:
        app.dependency_overrides.clear()


def _patch_google_http(monkeypatch: pytest.MonkeyPatch, *, userinfo: dict) -> None:
    import app.core.oauth.client as client_module
    import app.services.google_oauth_service as service_module

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in request.url.path:
            return httpx.Response(200, json=_TOKEN_RESPONSE)
        if "userinfo" in request.url.path:
            return httpx.Response(200, json=userinfo)
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)
    monkeypatch.setattr(service_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_start_redirects_to_google_with_state(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/v1/auth/google/start")
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    params = parse_qs(urlparse(location).query)
    assert params["client_id"] == ["gcid"]
    assert "state" in params


@pytest.mark.asyncio
async def test_callback_with_no_code_redirects_to_login_with_error(
    api_client: AsyncClient,
) -> None:
    r = await api_client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://app.test/login")
    assert parse_qs(urlparse(location).query)["error"] == ["google_oauth_failed"]
    assert SESSION_COOKIE_NAME not in r.cookies


@pytest.mark.asyncio
async def test_callback_with_a_tampered_state_redirects_to_login_with_error(
    api_client: AsyncClient,
) -> None:
    r = await api_client.get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": "not-a-real-token"}
    )
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://app.test/login")
    assert parse_qs(urlparse(location).query)["error"] == ["google_oauth_failed"]


@pytest.mark.asyncio
async def test_callback_with_a_valid_new_signup_sets_session_cookies_and_redirects(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.google_oauth_service import create_login_state_token

    email = f"newuser-{uuid.uuid4().hex[:8]}@example.com"
    _patch_google_http(
        monkeypatch,
        userinfo={
            "sub": f"sub-{uuid.uuid4().hex[:8]}",
            "email": email,
            "email_verified": True,
            "name": "New User",
        },
    )
    state = create_login_state_token(secret_key=_settings().secret_key.get_secret_value())

    r = await api_client.get(
        "/api/v1/auth/google/callback", params={"code": "the-code", "state": state}
    )

    assert r.status_code == 302
    assert r.headers["location"] == "https://app.test/dashboard"
    assert SESSION_COOKIE_NAME in r.cookies
    assert CSRF_COOKIE_NAME in r.cookies


@pytest.mark.asyncio
async def test_callback_with_an_unverified_google_email_redirects_to_login_with_error(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.google_oauth_service import create_login_state_token

    _patch_google_http(
        monkeypatch,
        userinfo={
            "sub": "sub-1",
            "email": "unverified@example.com",
            "email_verified": False,
            "name": "Unverified",
        },
    )
    state = create_login_state_token(secret_key=_settings().secret_key.get_secret_value())

    r = await api_client.get(
        "/api/v1/auth/google/callback", params={"code": "the-code", "state": state}
    )

    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://app.test/login")
    assert parse_qs(urlparse(location).query)["error"] == ["google_oauth_failed"]
    assert SESSION_COOKIE_NAME not in r.cookies
