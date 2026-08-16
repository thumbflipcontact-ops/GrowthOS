"""Integration tests for AgentLifecycleSweep — see app/core/agent_lifecycle.py.

Two independent disable reasons (not-entitled, 48h inactivity), the is_comped exemption from
both, notification behavior (sent when Resend is configured, gracefully skipped/never blocking
the disable otherwise), and that the disable itself goes through AgentConfigService.upsert with
a null actor and an "agent_config.auto_disabled" audit action.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.agent_lifecycle import INACTIVITY_THRESHOLD, AgentLifecycleSweep
from app.core.config import Settings
from app.core.entitlements import NO_CARD_TRIAL_DAYS
from app.models.agent import AgentConfig
from app.models.audit import AuditLog
from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import MembershipRepository, UserRepository

pytestmark = pytest.mark.integration

_EXPIRED_TRIAL_CREATED_AT = datetime.now(UTC) - timedelta(days=NO_CARD_TRIAL_DAYS + 1)


def _settings(monkeypatch: pytest.MonkeyPatch, *, with_resend: bool = False) -> Settings:
    kwargs = dict(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
    )
    if with_resend:
        kwargs["resend_api_key"] = "re_test_key"
        kwargs["resend_from_email"] = "Threadly <notifications@usethreadly.co>"
    return Settings(**kwargs)


async def _make_org(
    db_session, *, created_at: datetime | None = None, is_comped: bool = False
) -> Organization:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name="Acme", slug=f"acme-lifecycle-{suffix}", is_comped=is_comped)
    if created_at is not None:
        org.created_at = created_at
    return await OrganizationRepository(db_session).add(org)


async def _make_project(db_session, org_id: uuid.UUID) -> Project:
    suffix = uuid.uuid4().hex[:8]
    return await ProjectRepository(db_session).add(
        Project(org_id=org_id, name="ScoutSEO", slug=f"scoutseo-lifecycle-{suffix}")
    )


async def _make_user_with_login(db_session, *, last_login_at: datetime | None) -> User:
    suffix = uuid.uuid4().hex[:8]
    return await UserRepository(db_session).add(
        User(
            email=f"u-{suffix}@example.com",
            name="Founder",
            password_hash="x",
            last_login_at=last_login_at,
        )
    )


async def _add_membership(db_session, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db_session.add(Membership(org_id=org_id, user_id=user_id, role=MembershipRole.OWNER))
    await db_session.flush()


async def _enabled_conversation_finder(db_session, project_id: uuid.UUID) -> AgentConfig:
    return await AgentConfigRepository(db_session).add(
        AgentConfig(
            project_id=project_id,
            agent_key="conversation_finder",
            config={"keywords": ["crawl budget"]},
            schedule_cron="0 */6 * * *",
            enabled=True,
        )
    )


def _patch_resend(monkeypatch: pytest.MonkeyPatch, handler):
    import app.core.email.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_disables_inactive_org_with_a_recently_active_entitled_org_left_alone(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch)
    org = await _make_org(db_session)  # fresh -> entitled via no-card trial
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(hours=1)
    )
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()

    assert disabled == 1
    await db_session.refresh(config)
    assert config.enabled is False


@pytest.mark.asyncio
async def test_leaves_recently_active_entitled_org_untouched(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    org = await _make_org(db_session)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(db_session, last_login_at=datetime.now(UTC))
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()

    assert disabled == 0
    await db_session.refresh(config)
    assert config.enabled is True


@pytest.mark.asyncio
async def test_disables_not_entitled_org_even_with_a_recent_login(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    org = await _make_org(db_session, created_at=_EXPIRED_TRIAL_CREATED_AT)  # trial elapsed
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(db_session, last_login_at=datetime.now(UTC))  # logged in just now
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()

    assert disabled == 1
    await db_session.refresh(config)
    assert config.enabled is False


@pytest.mark.asyncio
async def test_comped_org_is_exempt_from_both_the_entitlement_and_inactivity_checks(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch)
    # Both conditions that would otherwise trigger a disable: elapsed trial, ancient login.
    org = await _make_org(db_session, created_at=_EXPIRED_TRIAL_CREATED_AT, is_comped=True)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(days=30)
    )
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()

    assert disabled == 0
    await db_session.refresh(config)
    assert config.enabled is True


@pytest.mark.asyncio
async def test_disable_is_audit_logged_with_a_null_actor(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    org = await _make_org(db_session, created_at=_EXPIRED_TRIAL_CREATED_AT)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(db_session, last_login_at=datetime.now(UTC))
    await _add_membership(db_session, org.id, user.id)
    await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    await sweep.run()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "agent_config.auto_disabled")
    )
    row = result.scalar_one()
    assert row.actor_user_id is None
    assert row.org_id == org.id


@pytest.mark.asyncio
async def test_org_with_multiple_members_judged_by_most_recent_login(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch)
    org = await _make_org(db_session)
    project = await _make_project(db_session, org.id)
    stale_user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(days=10)
    )
    active_user = await _make_user_with_login(db_session, last_login_at=datetime.now(UTC))
    await _add_membership(db_session, org.id, stale_user.id)
    await _add_membership(db_session, org.id, active_user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()

    assert disabled == 0  # one active member is enough to keep it alive
    await db_session.refresh(config)
    assert config.enabled is True


@pytest.mark.asyncio
async def test_sends_a_notification_email_when_resend_is_configured(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org = await _make_org(db_session)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(hours=1)
    )
    await _add_membership(db_session, org.id, user.id)
    await _enabled_conversation_finder(db_session, project.id)

    sent_to: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_to.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer re_test_key"
        return httpx.Response(200, json={"id": "email_123"})

    _patch_resend(monkeypatch, handler)

    sweep = AgentLifecycleSweep(db_session, settings)
    await sweep.run()

    assert sent_to == ["/emails"]


@pytest.mark.asyncio
async def test_email_failure_does_not_block_the_disable(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org = await _make_org(db_session)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(hours=1)
    )
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    _patch_resend(monkeypatch, handler)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()  # must not raise

    assert disabled == 1
    await db_session.refresh(config)
    assert config.enabled is False


@pytest.mark.asyncio
async def test_missing_resend_settings_skips_notification_without_raising(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch, with_resend=False)
    org = await _make_org(db_session)
    project = await _make_project(db_session, org.id)
    user = await _make_user_with_login(
        db_session, last_login_at=datetime.now(UTC) - INACTIVITY_THRESHOLD - timedelta(hours=1)
    )
    await _add_membership(db_session, org.id, user.id)
    config = await _enabled_conversation_finder(db_session, project.id)

    sweep = AgentLifecycleSweep(db_session, settings)
    disabled = await sweep.run()  # must not raise despite no Resend config

    assert disabled == 1
    await db_session.refresh(config)
    assert config.enabled is False


@pytest.mark.asyncio
async def test_most_recent_login_at_repository_method(db_session) -> None:
    org = await _make_org(db_session)
    older = datetime.now(UTC) - timedelta(days=3)
    newer = datetime.now(UTC) - timedelta(hours=1)
    user_a = await _make_user_with_login(db_session, last_login_at=older)
    user_b = await _make_user_with_login(db_session, last_login_at=newer)
    await _add_membership(db_session, org.id, user_a.id)
    await _add_membership(db_session, org.id, user_b.id)

    repo = MembershipRepository(db_session)
    result = await repo.most_recent_login_at(org.id)

    assert result is not None
    assert abs((result - newer).total_seconds()) < 1
