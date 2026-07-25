"""The optimistic-concurrency guard on content_items — the mechanism ARCHITECTURE.md §8 and
docs/reviews/DESIGN_REVIEW.md §3.2 identified as necessary to prevent a double-approval race.
ContentApprovalService itself is out of Phase 1 scope (business logic — see ROADMAP.md), but
the database-level primitive it will be built on is exactly what's tested here: a
compare-and-swap update against `version` correctly allows exactly one of two concurrent
transitions to succeed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.models.content import ContentItem, ContentItemStatus
from app.models.identity import Organization
from app.models.project import Project

pytestmark = pytest.mark.integration


async def _make_content_item(db_session) -> ContentItem:
    org = Organization(name="Acme", slug="acme-cas")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug="p-cas")
    db_session.add(project)
    await db_session.flush()
    item = ContentItem(project_id=project.id, type="dummy_reply", body="hello")
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_compare_and_swap_update_succeeds_with_correct_version(db_session) -> None:
    item = await _make_content_item(db_session)
    assert item.version == 1

    result = await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == 1)
        .values(status=ContentItemStatus.PENDING_REVIEW, version=2)
    )
    assert result.rowcount == 1


@pytest.mark.asyncio
async def test_compare_and_swap_update_fails_with_stale_version(db_session) -> None:
    """This is the case that matters: two concurrent "approve" requests both reading
    version=2, only one of which should be allowed to win. The second, using the now-stale
    version, must affect zero rows — the service layer surfaces that as a 409, never a
    silent double-transition."""
    item = await _make_content_item(db_session)
    await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == 1)
        .values(status=ContentItemStatus.PENDING_REVIEW, version=2)
    )

    stale_result = await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == 1)  # stale — already 2 now
        .values(status=ContentItemStatus.APPROVED, version=3)
    )
    assert stale_result.rowcount == 0

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.PENDING_REVIEW
    assert item.version == 2


@pytest.mark.asyncio
async def test_two_racing_approvals_exactly_one_wins(db_session) -> None:
    item = await _make_content_item(db_session)
    await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == 1)
        .values(status=ContentItemStatus.PENDING_REVIEW, version=2)
    )
    await db_session.refresh(item)
    read_version = item.version  # both racing requests "read" this same version

    first = await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == read_version)
        .values(status=ContentItemStatus.APPROVED, version=read_version + 1)
    )
    second = await db_session.execute(
        update(ContentItem)
        .where(ContentItem.id == item.id, ContentItem.version == read_version)
        .values(status=ContentItemStatus.REJECTED, version=read_version + 1)
    )

    assert (first.rowcount, second.rowcount) in {(1, 0), (0, 1)}
    await db_session.refresh(item)
    assert item.status in (ContentItemStatus.APPROVED, ContentItemStatus.REJECTED)
