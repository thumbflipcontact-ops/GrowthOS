"""Integration tests for ContentApprovalService — see app/services/content_approval.py and
ARCHITECTURE.md §8. Uses a real Postgres transaction so the atomic CAS `UPDATE` (status +
version guarded in one WHERE clause) is exercised for real, not mocked.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import InvalidStateTransition, NotFoundError
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus
from app.models.identity import Organization, User
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.content_approval import ContentApprovalService

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-appr-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-appr-{suffix}")
    )


async def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:8]
    return await UserRepository(db_session).add(
        User(email=f"u-{suffix}@example.com", name="U", password_hash="x")
    )


async def _make_content_item(
    db_session, project: Project, *, status: ContentItemStatus = ContentItemStatus.PENDING_REVIEW
) -> ContentItem:
    item = ContentItem(
        project_id=project.id,
        type="reddit_reply",
        status=status,
        body="A helpful reply.",
        confidence=Decimal("0.75"),
    )
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_approve_transitions_pending_review_to_approved(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project)
    original_version = item.version  # `item` and `updated` are the same identity-mapped
    # object — read this before approve() refreshes it in place, or it'll reflect the
    # post-transition value too.
    service = ContentApprovalService(db_session)

    updated = await service.approve(
        project_id=project.id,
        item_id=item.id,
        expected_version=original_version,
        actor_user_id=user.id,
        org_id=project.org_id,
    )

    assert updated.status == ContentItemStatus.APPROVED
    assert updated.reviewed_by_user_id == user.id
    assert updated.reviewed_at is not None
    assert updated.version == original_version + 1

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.approved")
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.target == str(item.id)
    assert audit.actor_user_id == user.id


@pytest.mark.asyncio
async def test_reject_requires_a_reason_and_records_it_in_the_audit_log(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project)
    service = ContentApprovalService(db_session)

    updated = await service.reject(
        project_id=project.id,
        item_id=item.id,
        expected_version=item.version,
        actor_user_id=user.id,
        org_id=project.org_id,
        reason="Too promotional.",
    )

    assert updated.status == ContentItemStatus.REJECTED

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.rejected")
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.metadata_ == {"reason": "Too promotional."}


@pytest.mark.asyncio
async def test_archive_is_allowed_from_draft_and_pending_review(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = ContentApprovalService(db_session)

    draft_item = await _make_content_item(db_session, project, status=ContentItemStatus.DRAFT)
    updated_draft = await service.archive(
        project_id=project.id,
        item_id=draft_item.id,
        expected_version=draft_item.version,
        actor_user_id=user.id,
        org_id=project.org_id,
    )
    assert updated_draft.status == ContentItemStatus.ARCHIVED

    pending_item = await _make_content_item(db_session, project)
    updated_pending = await service.archive(
        project_id=project.id,
        item_id=pending_item.id,
        expected_version=pending_item.version,
        actor_user_id=user.id,
        org_id=project.org_id,
        reason="No longer relevant.",
    )
    assert updated_pending.status == ContentItemStatus.ARCHIVED


@pytest.mark.asyncio
async def test_approve_rejects_an_item_still_in_draft(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project, status=ContentItemStatus.DRAFT)
    service = ContentApprovalService(db_session)

    with pytest.raises(InvalidStateTransition):
        await service.approve(
            project_id=project.id,
            item_id=item.id,
            expected_version=item.version,
            actor_user_id=user.id,
            org_id=project.org_id,
        )


@pytest.mark.asyncio
async def test_approve_rejects_an_already_approved_item(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project, status=ContentItemStatus.APPROVED)
    service = ContentApprovalService(db_session)

    with pytest.raises(InvalidStateTransition):
        await service.approve(
            project_id=project.id,
            item_id=item.id,
            expected_version=item.version,
            actor_user_id=user.id,
            org_id=project.org_id,
        )


@pytest.mark.asyncio
async def test_archive_rejects_an_already_published_item(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project, status=ContentItemStatus.PUBLISHED)
    service = ContentApprovalService(db_session)

    with pytest.raises(InvalidStateTransition):
        await service.archive(
            project_id=project.id,
            item_id=item.id,
            expected_version=item.version,
            actor_user_id=user.id,
            org_id=project.org_id,
        )


@pytest.mark.asyncio
async def test_approve_rejects_a_stale_version(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project)
    service = ContentApprovalService(db_session)

    with pytest.raises(InvalidStateTransition):
        await service.approve(
            project_id=project.id,
            item_id=item.id,
            expected_version=item.version + 1,  # wrong on purpose
            actor_user_id=user.id,
            org_id=project.org_id,
        )


@pytest.mark.asyncio
async def test_concurrent_approve_and_reject_only_one_wins(db_session) -> None:
    """The exact race docs/api/API_DESIGN.md's approval endpoints are documented to guard
    against: two racing requests reading the same version — exactly one succeeds."""
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project)
    original_version = item.version  # both racing requests read this same version
    service = ContentApprovalService(db_session)

    approved = await service.approve(
        project_id=project.id,
        item_id=item.id,
        expected_version=original_version,
        actor_user_id=user.id,
        org_id=project.org_id,
    )
    assert approved.status == ContentItemStatus.APPROVED

    with pytest.raises(InvalidStateTransition):
        await service.reject(
            project_id=project.id,
            item_id=item.id,
            expected_version=original_version,  # stale now — approve() already bumped it
            actor_user_id=user.id,
            org_id=project.org_id,
            reason="too late",
        )


@pytest.mark.asyncio
async def test_approve_404s_for_an_item_in_a_different_project(db_session) -> None:
    project_a = await _make_project(db_session)
    project_b = await _make_project(db_session)
    user = await _make_user(db_session)
    item = await _make_content_item(db_session, project_a)
    service = ContentApprovalService(db_session)

    with pytest.raises(NotFoundError):
        await service.approve(
            project_id=project_b.id,
            item_id=item.id,
            expected_version=item.version,
            actor_user_id=user.id,
            org_id=project_b.org_id,
        )


@pytest.mark.asyncio
async def test_approve_404s_for_an_unknown_item(db_session) -> None:
    project = await _make_project(db_session)
    user = await _make_user(db_session)
    service = ContentApprovalService(db_session)

    with pytest.raises(NotFoundError):
        await service.approve(
            project_id=project.id,
            item_id=uuid.uuid4(),
            expected_version=1,
            actor_user_id=user.id,
            org_id=project.org_id,
        )
