"""Integration tests for OAuthConnectionService — see docs/auth/OAUTH2_ARCHITECTURE.md §3
and ADR 0011. Uses httpx.MockTransport (via monkeypatching app.core.oauth.client's
AsyncClient, same technique as test_oauth_client.py) so no real network call ever happens,
while still exercising the real HTTP request/response path through OAuthClient.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AuthenticationError, NotFoundError, PluginError, ValidationError
from app.core.oauth.state import OAuthState, create_state_token
from app.core.plugin_catalog import PluginCatalog
from app.models.audit import AuditLog
from app.models.identity import Organization, User
from app.models.plugin import PluginConnection, PluginConnectionStatus
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.plugin_repository import PluginConnectionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.oauth_connection import OAuthConnectionService

pytestmark = pytest.mark.integration

SPEC = OAuthProviderSpec(
    authorize_url="https://provider.invalid/authorize",
    token_url="https://provider.invalid/token",
    revoke_url="https://provider.invalid/revoke",
    scopes=("read",),
)

MANIFEST = PluginManifest(
    key="testoauth",
    interface_version="1.0",
    capabilities=("searchable",),
    auth_type="oauth2",
    oauth=SPEC,
)

NON_OAUTH_MANIFEST = PluginManifest(
    key="testapikey", interface_version="1.0", capabilities=("searchable",), auth_type="api_key"
)


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_SECRET", "csecret")
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
    )


def _catalog() -> PluginCatalog:
    catalog = PluginCatalog()
    catalog.refresh([MANIFEST, NON_OAUTH_MANIFEST])
    return catalog


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(Organization(name="Acme", slug=f"acme-{suffix}"))
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-{suffix}")
    )


async def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:8]
    return await UserRepository(db_session).add(
        User(email=f"user-{suffix}@example.com", name="Test User", password_hash="x")
    )


def _patch_token_endpoint(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import app.core.oauth.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


def _success_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "read",
        },
    )


# --- start() ---------------------------------------------------------------------------


def test_start_returns_an_authorize_url_with_state(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    service = OAuthConnectionService(session=None, catalog=_catalog(), settings=settings)  # type: ignore[arg-type]

    url = service.start(
        project_id=uuid.uuid4(), plugin_key="testoauth", label="default", user_id=uuid.uuid4()
    )

    assert url.startswith(SPEC.authorize_url)
    assert "state=" in url
    assert "client_id=cid" in url


def test_start_rejects_unknown_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    service = OAuthConnectionService(session=None, catalog=_catalog(), settings=settings)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError):
        service.start(
            project_id=uuid.uuid4(), plugin_key="nope", label="default", user_id=uuid.uuid4()
        )


def test_start_rejects_a_non_oauth2_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    service = OAuthConnectionService(session=None, catalog=_catalog(), settings=settings)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        service.start(
            project_id=uuid.uuid4(), plugin_key="testapikey", label="default", user_id=uuid.uuid4()
        )


# --- handle_callback() ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_callback_creates_a_new_connection(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id
    _patch_token_endpoint(monkeypatch, _success_handler)

    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    connection = await service.handle_callback(
        code="the-code", state_token=state_token, current_user_id=user_id
    )

    assert connection.status == PluginConnectionStatus.CONNECTED
    assert connection.plugin_key == "testoauth"
    assert connection.label == "default"
    assert connection.token_expires_at is not None
    assert connection.granted_scopes == ["read"]
    assert connection.credentials_encrypted is not None
    assert connection.credential_data_key_wrapped is not None


@pytest.mark.asyncio
async def test_handle_callback_writes_an_audit_log_row(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id
    _patch_token_endpoint(monkeypatch, _success_handler)

    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    await service.handle_callback(code="the-code", state_token=state_token, current_user_id=user_id)

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.oauth_connected")
    )
    row = result.scalar_one()
    assert row.org_id == project.org_id
    assert row.actor_user_id == user_id
    assert row.target == "testoauth"


@pytest.mark.asyncio
async def test_handle_callback_reconnect_updates_the_same_row(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id
    _patch_token_endpoint(monkeypatch, _success_handler)

    def _state_token() -> str:
        state = OAuthState(
            project_id=project.id,
            plugin_key="testoauth",
            label="default",
            user_id=user_id,
            code_verifier=None,
            nonce=str(uuid.uuid4()),
        )
        return create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    first = await service.handle_callback(
        code="code-1", state_token=_state_token(), current_user_id=user_id
    )
    first_id = first.id

    second = await service.handle_callback(
        code="code-2", state_token=_state_token(), current_user_id=user_id
    )

    assert second.id == first_id  # same row, not a duplicate

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.oauth_reconnected")
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_handle_callback_rejects_invalid_state(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    service = OAuthConnectionService(db_session, _catalog(), settings)

    with pytest.raises(AuthenticationError):
        await service.handle_callback(
            code="c", state_token="not-a-real-token", current_user_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_handle_callback_rejects_state_with_wrong_user(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=uuid.uuid4(),
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    with pytest.raises(AuthenticationError):
        await service.handle_callback(
            code="c", state_token=state_token, current_user_id=uuid.uuid4()  # different user
        )


@pytest.mark.asyncio
async def test_handle_callback_rejects_deleted_project(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    user_id = (await _make_user(db_session)).id
    state = OAuthState(
        project_id=uuid.uuid4(),  # never created
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    with pytest.raises(NotFoundError):
        await service.handle_callback(code="c", state_token=state_token, current_user_id=user_id)


@pytest.mark.asyncio
async def test_handle_callback_wraps_token_exchange_failure(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_request"})

    _patch_token_endpoint(monkeypatch, failing_handler)

    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    with pytest.raises(PluginError):
        await service.handle_callback(code="c", state_token=state_token, current_user_id=user_id)


@pytest.mark.asyncio
async def test_handle_callback_supports_multiple_labels_for_the_same_plugin(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id
    _patch_token_endpoint(monkeypatch, _success_handler)

    def _state_token(label: str) -> str:
        state = OAuthState(
            project_id=project.id,
            plugin_key="testoauth",
            label=label,
            user_id=user_id,
            code_verifier=None,
            nonce=str(uuid.uuid4()),
        )
        return create_state_token(state, secret_key=settings.secret_key.get_secret_value())

    service = OAuthConnectionService(db_session, _catalog(), settings)
    default_conn = await service.handle_callback(
        code="c1", state_token=_state_token("default"), current_user_id=user_id
    )
    second_conn = await service.handle_callback(
        code="c2", state_token=_state_token("second-account"), current_user_id=user_id
    )

    assert default_conn.id != second_conn.id
    assert default_conn.label == "default"
    assert second_conn.label == "second-account"


# --- disconnect() ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_clears_credentials_and_calls_revoke(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id

    revoke_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/revoke":
            revoke_calls.append(request.content.decode())
            return httpx.Response(200)
        return _success_handler(request)

    _patch_token_endpoint(monkeypatch, handler)

    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())
    service = OAuthConnectionService(db_session, _catalog(), settings)
    connection = await service.handle_callback(
        code="c", state_token=state_token, current_user_id=user_id
    )

    await service.disconnect(connection=connection, org_id=project.org_id, actor_user_id=user_id)

    assert connection.status == PluginConnectionStatus.DISCONNECTED
    assert connection.credentials_encrypted is None
    assert connection.credential_data_key_wrapped is None
    assert connection.token_expires_at is None
    assert connection.granted_scopes == []
    assert len(revoke_calls) == 1
    assert "token=at-1" in revoke_calls[0]


@pytest.mark.asyncio
async def test_disconnect_succeeds_even_if_revoke_fails(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/revoke":
            raise httpx.ConnectError("unreachable")
        return _success_handler(request)

    _patch_token_endpoint(monkeypatch, handler)

    state = OAuthState(
        project_id=project.id,
        plugin_key="testoauth",
        label="default",
        user_id=user_id,
        code_verifier=None,
        nonce="n",
    )
    state_token = create_state_token(state, secret_key=settings.secret_key.get_secret_value())
    service = OAuthConnectionService(db_session, _catalog(), settings)
    connection = await service.handle_callback(
        code="c", state_token=state_token, current_user_id=user_id
    )

    await service.disconnect(connection=connection, org_id=project.org_id, actor_user_id=user_id)

    assert connection.status == PluginConnectionStatus.DISCONNECTED  # still succeeded locally


@pytest.mark.asyncio
async def test_disconnect_writes_an_audit_log_row(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id
    _patch_token_endpoint(monkeypatch, _success_handler)

    connection = PluginConnection(project_id=project.id, plugin_key="testoauth", label="default")
    connection = await PluginConnectionRepository(db_session).add(connection)

    service = OAuthConnectionService(db_session, _catalog(), settings)
    await service.disconnect(connection=connection, org_id=project.org_id, actor_user_id=user_id)

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.oauth_disconnected")
    )
    row = result.scalar_one()
    assert row.target == "testoauth"
    assert row.actor_user_id == user_id


@pytest.mark.asyncio
async def test_disconnect_with_no_prior_credentials_never_calls_revoke(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    user_id = (await _make_user(db_session)).id

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    _patch_token_endpoint(monkeypatch, handler)

    connection = PluginConnection(project_id=project.id, plugin_key="testoauth", label="default")
    connection = await PluginConnectionRepository(db_session).add(connection)

    service = OAuthConnectionService(db_session, _catalog(), settings)
    await service.disconnect(connection=connection, org_id=project.org_id, actor_user_id=user_id)

    assert called is False
