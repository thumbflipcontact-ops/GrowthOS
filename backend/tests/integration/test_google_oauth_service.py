"""Integration tests for GoogleOAuthService — see app/services/google_oauth_service.py.
Uses httpx.MockTransport (same technique as test_oauth_connection_service.py) patched onto
both httpx-using call sites here: app.core.oauth.client (the token exchange, shared with the
plugin OAuth framework) and app.services.google_oauth_service itself (the userinfo call).
"""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.oauth.errors import OAuthClientNotConfigured
from app.models.identity import Membership, Organization, User
from app.models.oauth_identity import OAuthIdentity
from app.repositories.user_repository import UserRepository
from app.services.google_oauth_service import (
    GoogleOAuthService,
    build_google_authorize_url,
    create_login_state_token,
)

pytestmark = pytest.mark.integration

_TOKEN_RESPONSE = {
    "access_token": "at-1",
    "token_type": "bearer",
    "expires_in": 3600,
    "scope": "openid email profile",
}


def _settings(*, configured: bool = True) -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        google_oauth_client_id="gcid" if configured else None,
        google_oauth_client_secret="gcsecret" if configured else None,
    )


def _patch_google_http(monkeypatch: pytest.MonkeyPatch, *, userinfo: dict | None) -> None:
    """Routes by URL to the right canned response — the token exchange (OAuthClient, inside
    app.core.oauth.client) and the userinfo call (inside app.services.google_oauth_service)
    are two separate httpx.AsyncClient instances in two different modules, both patched here."""
    import app.core.oauth.client as client_module
    import app.services.google_oauth_service as service_module

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in request.url.path:
            return httpx.Response(200, json=_TOKEN_RESPONSE)
        if "userinfo" in request.url.path:
            if userinfo is None:
                return httpx.Response(500, json={"error": "server_error"})
            return httpx.Response(200, json=userinfo)
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)
    monkeypatch.setattr(service_module.httpx, "AsyncClient", fake_async_client)


def _google_profile(*, sub: str, email: str, name: str = "Ada Lovelace", verified: bool = True) -> dict:
    return {"sub": sub, "email": email, "email_verified": verified, "name": name}


def _valid_state(settings: Settings) -> str:
    return create_login_state_token(secret_key=settings.secret_key.get_secret_value())


# --- build_google_authorize_url --------------------------------------------------------


def test_build_google_authorize_url_includes_state_and_scopes(_migrated_db: str) -> None:
    # _migrated_db (unused directly) is what makes DATABASE_URL exist in the environment at
    # all when this file runs in isolation — see its own session-scoped fixture in
    # conftest.py; a test with no db_session param never triggers it otherwise, and
    # app.main's import chain (pulled in by the autouse rate-limiter fixture) needs it.
    settings = _settings()
    url = build_google_authorize_url(settings)
    params = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert params["client_id"] == ["gcid"]
    assert params["scope"] == ["openid email profile"]
    assert "state" in params


def test_build_google_authorize_url_raises_when_not_configured(_migrated_db: str) -> None:
    settings = _settings(configured=False)
    with pytest.raises(OAuthClientNotConfigured):
        build_google_authorize_url(settings)


# --- handle_callback ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_callback_creates_a_new_user_and_org_for_a_first_time_signup(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    sub = f"google-sub-{uuid.uuid4().hex[:8]}"
    email = f"ada-{uuid.uuid4().hex[:8]}@example.com"
    _patch_google_http(monkeypatch, userinfo=_google_profile(sub=sub, email=email))

    service = GoogleOAuthService(db_session, settings)
    user = await service.handle_callback(code="the-code", state_token=_valid_state(settings))

    assert user.email == email
    assert user.name == "Ada Lovelace"
    assert user.password_hash is None
    assert user.email_verified_at is not None  # Google already verified it — no separate step
    assert user.last_login_at is not None

    identity = (
        await db_session.execute(
            select(OAuthIdentity).where(OAuthIdentity.provider_user_id == sub)
        )
    ).scalar_one()
    assert identity.user_id == user.id

    membership = (
        await db_session.execute(select(Membership).where(Membership.user_id == user.id))
    ).scalar_one()
    org = await db_session.get(Organization, membership.org_id)
    assert org is not None
    assert org.name == "Ada Lovelace's Workspace"


@pytest.mark.asyncio
async def test_handle_callback_logs_in_an_existing_google_identity_without_duplicating_anything(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    sub = f"google-sub-{uuid.uuid4().hex[:8]}"
    email = f"ada-{uuid.uuid4().hex[:8]}@example.com"
    _patch_google_http(monkeypatch, userinfo=_google_profile(sub=sub, email=email))
    service = GoogleOAuthService(db_session, settings)
    first = await service.handle_callback(code="c1", state_token=_valid_state(settings))

    second = await service.handle_callback(code="c2", state_token=_valid_state(settings))

    assert second.id == first.id
    users = (
        await db_session.execute(select(User).where(User.email == email))
    ).scalars().all()
    assert len(users) == 1
    identities = (
        await db_session.execute(
            select(OAuthIdentity).where(OAuthIdentity.provider_user_id == sub)
        )
    ).scalars().all()
    assert len(identities) == 1


@pytest.mark.asyncio
async def test_handle_callback_links_google_to_an_existing_password_account_by_verified_email(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"existing-{uuid.uuid4().hex[:8]}@example.com"
    existing = await UserRepository(db_session).add(
        User(email=email, name="Existing Name", password_hash="argon2-hash", email_verified_at=None)
    )
    settings = _settings()
    sub = f"google-sub-{uuid.uuid4().hex[:8]}"
    _patch_google_http(monkeypatch, userinfo=_google_profile(sub=sub, email=email))

    service = GoogleOAuthService(db_session, settings)
    user = await service.handle_callback(code="the-code", state_token=_valid_state(settings))

    assert user.id == existing.id
    assert user.password_hash == "argon2-hash"  # untouched — still has a password too
    assert user.email_verified_at is not None  # Google's verification filled the gap

    identity = (
        await db_session.execute(
            select(OAuthIdentity).where(OAuthIdentity.provider_user_id == sub)
        )
    ).scalar_one()
    assert identity.user_id == existing.id


@pytest.mark.asyncio
async def test_handle_callback_rejects_an_unverified_google_email(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    email = f"unverified-{uuid.uuid4().hex[:8]}@example.com"
    _patch_google_http(
        monkeypatch, userinfo=_google_profile(sub="s1", email=email, verified=False)
    )
    service = GoogleOAuthService(db_session, settings)

    with pytest.raises(AuthenticationError):
        await service.handle_callback(code="the-code", state_token=_valid_state(settings))

    assert await UserRepository(db_session).get_by_email(email) is None


@pytest.mark.asyncio
async def test_handle_callback_rejects_an_invalid_state_token(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    # No HTTP patch at all — a bad state must be rejected before any network call is made.
    service = GoogleOAuthService(db_session, settings)

    with pytest.raises(AuthenticationError):
        await service.handle_callback(code="the-code", state_token="not-a-real-token")


@pytest.mark.asyncio
async def test_handle_callback_wraps_a_token_exchange_failure(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()

    import app.core.oauth.client as client_module

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(failing_handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)
    service = GoogleOAuthService(db_session, settings)

    with pytest.raises(AuthenticationError):
        await service.handle_callback(code="bad-code", state_token=_valid_state(settings))
