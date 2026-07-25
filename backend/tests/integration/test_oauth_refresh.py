"""Integration tests for OAuthRefreshSweep — see docs/auth/OAUTH2_ARCHITECTURE.md §5.2, §6.

Note on concurrency coverage: the sweep's `FOR UPDATE SKIP LOCKED` query (see
app/core/oauth/refresh.py) is deliberately NOT exercised here against two genuinely
concurrent transactions — this test module's db_session fixture is a single
transaction/savepoint per test (see conftest.py), and simulating real row-level lock
contention needs a second, independent connection to the same database outside that
savepoint. That's real, deliberately deferred test infrastructure — see
docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md for this called out as a known gap, not a
silent omission. What's covered here instead: the query correctly selects/excludes
candidates by status and expiry, and every refresh outcome (success, permanent failure,
transient failure, missing refresh token) is handled correctly against one session.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec
from sqlalchemy import select

from app.core.config import Settings
from app.core.crypto import derive_master_key, envelope_decrypt, envelope_encrypt
from app.core.oauth.refresh import REFRESH_WINDOW, OAuthRefreshSweep
from app.models.audit import AuditLog
from app.models.identity import Organization
from app.models.plugin import PluginCapability, PluginConnection, PluginConnectionStatus
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.plugin_repository import PluginConnectionRepository
from app.repositories.project_repository import ProjectRepository

pytestmark = pytest.mark.integration

SPEC = OAuthProviderSpec(
    authorize_url="https://provider.invalid/authorize",
    token_url="https://provider.invalid/token",
    scopes=("read",),
)
MANIFEST = PluginManifest(
    key="testoauth", interface_version="1.0", capabilities=("searchable",), auth_type="oauth2", oauth=SPEC
)

MASTER_KEY_SECRET = "test-master-key"


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_SECRET", "csecret")
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key=MASTER_KEY_SECRET,
    )


def _catalog():
    from app.core.plugin_catalog import PluginCatalog

    catalog = PluginCatalog()
    catalog.refresh([MANIFEST])
    return catalog


def _patch_token_endpoint(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import app.core.oauth.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(Organization(name="Acme", slug=f"acme-{suffix}"))
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="P", slug=f"p-{suffix}")
    )


async def _make_connection(
    db_session,
    *,
    project_id: uuid.UUID,
    access_token: str = "old-at",
    refresh_token: str | None = "old-rt",
    expires_at: datetime,
    status: PluginConnectionStatus = PluginConnectionStatus.CONNECTED,
    label: str = "default",
) -> PluginConnection:
    master_key = derive_master_key(MASTER_KEY_SECRET)
    payload = json.dumps(
        {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}
    ).encode()
    ciphertext, wrapped = envelope_encrypt(master_key, payload)
    connection = PluginConnection(
        project_id=project_id,
        plugin_key="testoauth",
        label=label,
        capabilities_enabled=[PluginCapability.SEARCHABLE],
        credentials_encrypted=ciphertext,
        credential_data_key_wrapped=wrapped,
        token_expires_at=expires_at,
        granted_scopes=["read"],
        status=status,
    )
    return await PluginConnectionRepository(db_session).add(connection)


def _decrypt(connection: PluginConnection) -> dict:
    master_key = derive_master_key(MASTER_KEY_SECRET)
    assert connection.credentials_encrypted is not None
    assert connection.credential_data_key_wrapped is not None
    plaintext = envelope_decrypt(
        master_key, connection.credentials_encrypted, connection.credential_data_key_wrapped
    )
    return json.loads(plaintext)


@pytest.mark.asyncio
async def test_refreshes_a_connection_expiring_soon(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    connection = await _make_connection(
        db_session,
        project_id=project.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),  # inside REFRESH_WINDOW
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "new-at",
                "refresh_token": "new-rt",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "read",
            },
        )

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 1
    await db_session.refresh(connection)
    assert connection.status == PluginConnectionStatus.CONNECTED
    assert connection.token_expires_at > datetime.now(UTC) + timedelta(minutes=30)
    stored = _decrypt(connection)
    assert stored["access_token"] == "new-at"
    assert stored["refresh_token"] == "new-rt"


@pytest.mark.asyncio
async def test_does_not_touch_a_connection_expiring_far_in_the_future(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    far_future = datetime.now(UTC) + timedelta(days=1)
    connection = await _make_connection(db_session, project_id=project.id, expires_at=far_future)

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"access_token": "should-not-happen", "expires_in": 60})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 0
    assert called is False
    await db_session.refresh(connection)
    assert connection.token_expires_at == far_future


@pytest.mark.asyncio
async def test_does_not_touch_a_disconnected_connection(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    await _make_connection(
        db_session,
        project_id=project.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        status=PluginConnectionStatus.DISCONNECTED,
    )

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 0


@pytest.mark.asyncio
async def test_permanent_failure_marks_connection_expired_and_writes_audit_log(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    connection = await _make_connection(
        db_session, project_id=project.id, expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 1
    await db_session.refresh(connection)
    assert connection.status == PluginConnectionStatus.EXPIRED

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.oauth_expired")
    )
    row = result.scalar_one()
    assert row.org_id == project.org_id
    assert row.target == "testoauth"


@pytest.mark.asyncio
async def test_transient_failure_leaves_connection_connected_for_retry(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    connection = await _make_connection(
        db_session, project_id=project.id, expires_at=datetime.now(UTC) + timedelta(minutes=1)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "temporarily_unavailable"})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 1  # attempted...
    await db_session.refresh(connection)
    assert connection.status == PluginConnectionStatus.CONNECTED  # ...but left CONNECTED, not EXPIRED

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "plugin_connection.oauth_expired")
    )
    assert result.scalar_one_or_none() is None  # no expiry audit event for a transient failure


@pytest.mark.asyncio
async def test_missing_refresh_token_marks_expired_without_a_network_call(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    connection = await _make_connection(
        db_session,
        project_id=project.id,
        refresh_token=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"access_token": "x", "expires_in": 60})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    await sweep.run()

    assert called is False
    await db_session.refresh(connection)
    assert connection.status == PluginConnectionStatus.EXPIRED


@pytest.mark.asyncio
async def test_preserves_old_refresh_token_when_provider_omits_a_new_one(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    connection = await _make_connection(
        db_session,
        project_id=project.id,
        refresh_token="the-original-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # No refresh_token in the response — some providers don't rotate it.
        return httpx.Response(200, json={"access_token": "new-at", "expires_in": 3600})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    await sweep.run()

    await db_session.refresh(connection)
    stored = _decrypt(connection)
    assert stored["access_token"] == "new-at"
    assert stored["refresh_token"] == "the-original-refresh-token"  # preserved, not nulled


@pytest.mark.asyncio
async def test_processes_multiple_due_connections_in_one_sweep(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    project = await _make_project(db_session)
    await _make_connection(
        db_session,
        project_id=project.id,
        label="a",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    await _make_connection(
        db_session,
        project_id=project.id,
        label="b",
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    await _make_connection(  # not due
        db_session,
        project_id=project.id,
        label="c",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})

    _patch_token_endpoint(monkeypatch, handler)

    sweep = OAuthRefreshSweep(db_session, _catalog(), settings)
    processed = await sweep.run()

    assert processed == 2


def test_refresh_window_is_generous_relative_to_the_job_cadence() -> None:
    # app/jobs/oauth_refresh.py's cron cadence is every 5 minutes — REFRESH_WINDOW must
    # exceed that so a token first becomes a candidate at least one cycle before expiry.
    assert REFRESH_WINDOW >= timedelta(minutes=5)
