"""Integration tests for the real `publish_content_item` job body — see
app/jobs/publish.py and ARCHITECTURE.md §8. Uses a small local fixture `Publishable` plugin
(same technique as test_plugin_registry_credential_resolution.py's `_EchoPlugin` — a fake
`plugins.<key>.plugin` module registered directly in `sys.modules`, no editable-install
ceremony needed) so this exercises the real `PluginRegistry.get(..., Publishable)` path
without needing Reddit's OAuth2 credential machinery.
"""

from __future__ import annotations

import sys
import types
import uuid
from decimal import Decimal

import pytest
from arq.worker import Retry
from plugins._shared.base import PublishResult
from plugins._shared.manifest import PluginManifest
from sqlalchemy import select

from app.core.config import Settings
from app.core.plugin_catalog import PluginCatalog
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus, ContentPublishAttempt
from app.models.event import DomainEvent
from app.models.identity import Organization
from app.models.plugin import PluginCapability, PluginConnection
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.plugin_repository import PluginConnectionRepository
from app.repositories.project_repository import ProjectRepository

pytestmark = pytest.mark.integration

_PLUGIN_KEY = "fake_publish"

_STATE: dict = {"success": True, "published_url": None, "error": None, "calls": []}


class _FakePublishPlugin:
    manifest = PluginManifest(
        key=_PLUGIN_KEY, interface_version="1.0", capabilities=("publishable",), auth_type="api_key"
    )

    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def publish(self, item: object) -> PublishResult:
        _STATE["calls"].append(item)
        if _STATE["success"]:
            return PublishResult(success=True, published_url=_STATE["published_url"], error=None)
        return PublishResult(success=False, published_url=None, error=_STATE["error"])

    async def health_check(self) -> bool:
        return True


def _install_fake_publish_module() -> None:
    module_name = f"plugins.{_PLUGIN_KEY}.plugin"
    module = types.ModuleType(module_name)
    module.create_plugin = lambda connection: _FakePublishPlugin(connection)  # type: ignore[attr-defined]
    sys.modules[module_name] = module


@pytest.fixture(autouse=True)
def _reset_state():
    _STATE["success"] = True
    _STATE["published_url"] = None
    _STATE["error"] = None
    _STATE["calls"] = []
    _install_fake_publish_module()
    yield
    del sys.modules[f"plugins.{_PLUGIN_KEY}.plugin"]


def _settings() -> Settings:
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
    catalog.refresh([_FakePublishPlugin.manifest])
    return catalog


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-pub-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-pub-{suffix}")
    )


async def _connect_fake_publish_plugin(db_session, project: Project) -> None:
    await PluginConnectionRepository(db_session).add(
        PluginConnection(
            project_id=project.id,
            plugin_key=_PLUGIN_KEY,
            capabilities_enabled=[PluginCapability.PUBLISHABLE],
        )
    )


async def _make_approved_item(db_session, project: Project, *, target_platform: str | None = _PLUGIN_KEY) -> ContentItem:
    item = ContentItem(
        project_id=project.id,
        type="reddit_reply",
        status=ContentItemStatus.APPROVED,
        body="A helpful reply.",
        confidence=Decimal("0.75"),
        target_platform=target_platform,
        target_ref="t3_abc123",
    )
    db_session.add(item)
    await db_session.flush()
    return item


def _ctx(session_factory_for) -> dict:
    return {"session_factory": session_factory_for, "settings": _settings(), "plugin_catalog": _catalog()}


@pytest.fixture
def publish_job(_migrated_db: str):
    """Imports app.jobs.publish lazily, after `_migrated_db` has already set DATABASE_URL in
    the environment — its WorkerSettings resolves get_settings() at module-import time,
    which would otherwise fail before that fixture runs."""
    from app.jobs.publish import publish_content_item

    return publish_content_item


@pytest.mark.asyncio
async def test_publish_succeeds_and_transitions_to_published(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    _STATE["published_url"] = "https://example.invalid/posted/1"
    project = await _make_project(db_session)
    await _connect_fake_publish_plugin(db_session, project)
    item = await _make_approved_item(db_session, project)

    await publish_content_item(_ctx(session_factory_for), str(item.id))

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.PUBLISHED
    assert item.published_at is not None
    assert item.publish_error is None

    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt).where(ContentPublishAttempt.content_item_id == item.id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].success is True
    assert attempts[0].attempt_number == 1
    assert attempts[0].published_url == "https://example.invalid/posted/1"

    events = (
        await db_session.execute(
            select(DomainEvent).where(DomainEvent.event_type == "content_item.published")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].payload["content_item_id"] == str(item.id)

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.published")
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.actor_user_id is None  # a system action, not a human one


@pytest.mark.asyncio
async def test_publish_failure_leaves_item_approved_with_error_and_raises_arq_retry(
    db_session, session_factory_for, publish_job
) -> None:
    """Also the regression test for docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1: this
    job used to re-raise a plain `PublishAttemptFailed` on failure, which Arq treats as a
    permanent failure after one attempt regardless of `max_tries` — only `arq.worker.Retry`
    actually triggers a retry. Asserting the raised type (not just "raises something") is
    what proves the fix."""
    publish_content_item = publish_job
    _STATE["success"] = False
    _STATE["error"] = "Reddit rejected the request: RATELIMIT"
    project = await _make_project(db_session)
    await _connect_fake_publish_plugin(db_session, project)
    item = await _make_approved_item(db_session, project)

    with pytest.raises(Retry):
        await publish_content_item(_ctx(session_factory_for), str(item.id))

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.APPROVED  # never auto-transitioned by a failure
    assert item.publish_error == "Reddit rejected the request: RATELIMIT"

    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt).where(ContentPublishAttempt.content_item_id == item.id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].success is False
    assert attempts[0].error == "Reddit rejected the request: RATELIMIT"

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.publish_failed")
        )
    ).scalar_one_or_none()
    assert audit is not None


@pytest.mark.asyncio
async def test_retrying_after_a_failure_increments_the_attempt_number(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    _STATE["success"] = False
    _STATE["error"] = "transient error"
    project = await _make_project(db_session)
    await _connect_fake_publish_plugin(db_session, project)
    item = await _make_approved_item(db_session, project)

    with pytest.raises(Retry):
        await publish_content_item(_ctx(session_factory_for), str(item.id))

    _STATE["success"] = True
    _STATE["published_url"] = "https://example.invalid/posted/2"
    await publish_content_item(_ctx(session_factory_for), str(item.id))

    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt)
            .where(ContentPublishAttempt.content_item_id == item.id)
            .order_by(ContentPublishAttempt.attempt_number)
        )
    ).scalars().all()
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert [a.success for a in attempts] == [False, True]

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.PUBLISHED


@pytest.mark.asyncio
async def test_publish_skips_an_item_that_is_not_approved(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    project = await _make_project(db_session)
    await _connect_fake_publish_plugin(db_session, project)
    item = await _make_approved_item(db_session, project)
    item.status = ContentItemStatus.PUBLISHED
    await db_session.flush()

    await publish_content_item(_ctx(session_factory_for), str(item.id))

    assert _STATE["calls"] == []  # never even called the plugin
    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt).where(ContentPublishAttempt.content_item_id == item.id)
        )
    ).scalars().all()
    assert attempts == []


@pytest.mark.asyncio
async def test_publish_is_a_noop_for_a_missing_item(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    await publish_content_item(_ctx(session_factory_for), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_publish_fails_clearly_when_target_platform_is_not_set(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    project = await _make_project(db_session)
    item = await _make_approved_item(db_session, project, target_platform=None)

    await publish_content_item(_ctx(session_factory_for), str(item.id))

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.APPROVED
    assert item.publish_error == "target_platform is not set"

    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt).where(ContentPublishAttempt.content_item_id == item.id)
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].success is False


@pytest.mark.asyncio
async def test_publish_fails_when_the_project_has_no_connection_for_the_target_platform(
    db_session, session_factory_for, publish_job
) -> None:
    publish_content_item = publish_job
    project = await _make_project(db_session)
    # deliberately not connecting the plugin
    item = await _make_approved_item(db_session, project)

    with pytest.raises(Retry):
        await publish_content_item(_ctx(session_factory_for), str(item.id))

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.APPROVED
    assert item.publish_error is not None


@pytest.mark.asyncio
async def test_publish_recovers_from_a_prior_successful_attempt_without_posting_again(
    db_session, session_factory_for, publish_job
) -> None:
    """Regression test for docs/reviews/PRODUCTION_READINESS_REVIEW.md R2: if a worker
    process crashes between a plugin's publish() call succeeding (a real, irreversible
    external post) and the transaction that would have recorded that success committing, the
    item is left `approved` even though it already posted. Simulated here by pre-inserting a
    successful ContentPublishAttempt row for an item that's still `approved` — exactly the
    state a crash in that window would leave behind. Re-running the job must reconcile using
    the recorded attempt, never call the plugin again."""
    publish_content_item = publish_job
    project = await _make_project(db_session)
    await _connect_fake_publish_plugin(db_session, project)
    item = await _make_approved_item(db_session, project)

    db_session.add(
        ContentPublishAttempt(
            content_item_id=item.id,
            attempt_number=1,
            success=True,
            published_url="https://example.invalid/posted/already",
            error=None,
        )
    )
    await db_session.flush()

    await publish_content_item(_ctx(session_factory_for), str(item.id))

    assert _STATE["calls"] == []  # never called the plugin a second time

    await db_session.refresh(item)
    assert item.status == ContentItemStatus.PUBLISHED
    assert item.publish_error is None

    # No second attempt row was created — the prior one is the only record, exactly as it
    # would be if the crash had never interrupted the original attempt's bookkeeping.
    attempts = (
        await db_session.execute(
            select(ContentPublishAttempt).where(ContentPublishAttempt.content_item_id == item.id)
        )
    ).scalars().all()
    assert len(attempts) == 1

    events = (
        await db_session.execute(
            select(DomainEvent).where(DomainEvent.event_type == "content_item.published")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].payload["published_url"] == "https://example.invalid/posted/already"

    audit = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "content_item.published")
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.metadata_["recovered_from_attempt"] == 1
