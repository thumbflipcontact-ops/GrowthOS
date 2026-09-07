"""Tests for DraftReadyNotificationSweep — see app/core/notifications.py. Mirrors
test_agent_lifecycle_sweep.py's technique exactly (a real db_session, httpx.MockTransport for
Resend) since this sweep is deliberately built the same way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.core.config import Settings
from app.core.notifications import DraftReadyNotificationSweep
from app.models.content import ContentItem, ContentItemStatus
from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.project import Project
from app.repositories.content_repository import ContentItemRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository

pytestmark = pytest.mark.integration


def _settings(monkeypatch: pytest.MonkeyPatch, *, with_resend: bool = False) -> Settings:
    kwargs = dict(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        frontend_origin="https://app.example.com",
    )
    if with_resend:
        kwargs["resend_api_key"] = "re_test_key"
        kwargs["resend_from_email"] = "Threadly <notifications@usethreadly.co>"
    return Settings(**kwargs)


async def _make_org_and_project(db_session) -> tuple[Organization, Project]:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-notify-{suffix}")
    )
    project = await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-notify-{suffix}")
    )
    return org, project


async def _make_member(db_session, org_id: uuid.UUID) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = await UserRepository(db_session).add(
        User(email=f"u-{suffix}@example.com", name="Founder", password_hash="x")
    )
    db_session.add(Membership(org_id=org_id, user_id=user.id, role=MembershipRole.OWNER))
    await db_session.flush()
    return user


async def _make_pending_review_item(db_session, project_id: uuid.UUID) -> ContentItem:
    item = ContentItem(
        project_id=project_id,
        type="reddit_reply",
        status=ContentItemStatus.PENDING_REVIEW,
        body="A helpful reply.",
        confidence=Decimal("0.75"),
    )
    return await ContentItemRepository(db_session).add(item)


def _patch_resend(monkeypatch: pytest.MonkeyPatch, handler):
    import app.core.email.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_batches_multiple_items_into_one_email_per_member(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org, project = await _make_org_and_project(db_session)
    user_a = await _make_member(db_session, org.id)
    user_b = await _make_member(db_session, org.id)
    await _make_pending_review_item(db_session, project.id)
    await _make_pending_review_item(db_session, project.id)

    captured_bodies: list[bytes] = []

    def capturing_handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(request.content)
        return httpx.Response(200, json={"id": "email_123"})

    _patch_resend(monkeypatch, capturing_handler)

    sweep = DraftReadyNotificationSweep(db_session, settings)
    notified = await sweep.run()

    assert notified == 1  # one project
    assert len(captured_bodies) == 2  # one email per member, not per item
    for body in captured_bodies:
        assert b"2 new" in body or b"2" in body  # count is batched into a single email


@pytest.mark.asyncio
async def test_never_renotifies_an_already_notified_item(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org, project = await _make_org_and_project(db_session)
    await _make_member(db_session, org.id)
    await _make_pending_review_item(db_session, project.id)

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": "email_123"})

    _patch_resend(monkeypatch, handler)

    sweep = DraftReadyNotificationSweep(db_session, settings)
    first_run = await sweep.run()
    second_run = await sweep.run(now=datetime.now(UTC) + timedelta(minutes=30))

    assert first_run == 1
    assert second_run == 0  # nothing new to notify about
    assert call_count == 1


@pytest.mark.asyncio
async def test_skips_projects_with_no_pending_items(db_session, monkeypatch) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org, project = await _make_org_and_project(db_session)
    await _make_member(db_session, org.id)
    # No pending_review items created at all.

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"id": "email_123"})

    _patch_resend(monkeypatch, handler)

    sweep = DraftReadyNotificationSweep(db_session, settings)
    notified = await sweep.run()

    assert notified == 0
    assert call_count == 0


@pytest.mark.asyncio
async def test_one_failed_send_does_not_block_the_rest_or_the_sweep(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch, with_resend=True)
    org, project = await _make_org_and_project(db_session)
    await _make_member(db_session, org.id)
    await _make_member(db_session, org.id)
    item = await _make_pending_review_item(db_session, project.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    _patch_resend(monkeypatch, handler)

    sweep = DraftReadyNotificationSweep(db_session, settings)
    notified = await sweep.run()  # must not raise

    assert notified == 1
    await db_session.refresh(item)
    assert item.notified_at is not None  # still marked, so it isn't retried forever


@pytest.mark.asyncio
async def test_missing_resend_settings_skips_notification_without_raising(
    db_session, monkeypatch
) -> None:
    settings = _settings(monkeypatch, with_resend=False)
    org, project = await _make_org_and_project(db_session)
    await _make_member(db_session, org.id)
    item = await _make_pending_review_item(db_session, project.id)

    sweep = DraftReadyNotificationSweep(db_session, settings)
    notified = await sweep.run()  # must not raise despite no Resend config

    assert notified == 1
    await db_session.refresh(item)
    assert item.notified_at is not None
