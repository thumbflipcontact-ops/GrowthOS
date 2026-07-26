"""The publish-jobs Arq worker. See docs/jobs/BACKGROUND_JOBS.md and ARCHITECTURE.md §8.

`publish_content_item` now has a real body: it is the *only* call site in the codebase that
invokes any plugin's `Publishable.publish()` (enforced structurally — `PluginRegistry.get`
raises `CapabilityNotSupported` for a plugin that doesn't implement `Publishable`, per
ARCHITECTURE.md §5), and the only code that ever writes `content_items.status = 'published'`.
Enqueued by `ContentApprovalService.approve()` via the API layer
(`app/api/v1/content_items.py`) with a deterministic `_job_id` (`f"publish-{content_item_id}"`)
so a duplicate enqueue (e.g. a retried API request) is a no-op while a publish attempt for
that item is already queued/running — see docs/reviews/PUBLISHING_WORKFLOW_IMPLEMENTATION_REPORT.md.

Every attempt — success or failure — is recorded as its own `content_publish_attempts` row
(the durable "publish history"), independent of whether Arq itself later retries. A failed
attempt leaves `content_items.status` at `approved` with `publish_error` set and re-raises,
so Arq's own retry/backoff policy (`WorkerSettings.max_tries` below) applies; after the final
retry is exhausted, the item stays `approved`+`publish_error`-populated — visible via the API
for a human to trigger a manual retry (`POST .../content-items/{id}/retry-publish`), never
silently dropped and never auto-transitioned to any other status by a failure.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings
from plugins._shared.base import Publishable
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import CapabilityNotSupported
from app.core.events import EventPublisher
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.core.plugin_registry import PluginRegistry
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus, ContentPublishAttempt
from app.models.project import Project
from app.repositories.content_repository import ContentPublishAttemptRepository
from app.repositories.plugin_repository import PluginConnectionRepository

logger = structlog.get_logger()


class PublishAttemptFailed(Exception):
    """Raised after a failed attempt has already been recorded, purely to trigger Arq's
    retry policy — never propagates past this module."""


async def publish_content_item(ctx: dict, content_item_id: str) -> None:
    session_factory = ctx["session_factory"]
    settings = ctx["settings"]
    catalog: PluginCatalog = ctx["plugin_catalog"]

    async with session_factory() as session:
        item = await session.get(ContentItem, uuid.UUID(content_item_id))
        if item is None:
            logger.warning("publish.item_missing", content_item_id=content_item_id)
            return

        # Race safety: the item may have moved on (e.g. a previous attempt in this same
        # retry sequence already succeeded, or — impossible today, but defensively checked
        # anyway — something else changed its status) between enqueue and this job running.
        if item.status != ContentItemStatus.APPROVED:
            logger.info(
                "publish.skipped_not_approved",
                content_item_id=content_item_id,
                status=item.status.value,
            )
            return

        project = await session.get(Project, item.project_id)
        if project is None:
            logger.error("publish.project_missing", content_item_id=content_item_id)
            return

        attempts = ContentPublishAttemptRepository(session)
        attempt_number = await attempts.next_attempt_number(item.id)

        if item.target_platform is None:
            # A structurally impossible-to-retry-into-success state (no plugin was ever
            # named) — record it, but don't raise: retrying the same job will hit the exact
            # same missing data every time. See "known limitations" in the implementation
            # report for why this can currently happen (no application-layer validation yet
            # requires target_platform to be set before a draft can be approved).
            await _record_attempt(
                session, item, attempt_number, success=False, error="target_platform is not set"
            )
            item.publish_error = "target_platform is not set"
            await session.commit()
            return

        connections = await PluginConnectionRepository(session).list_by_project(item.project_id)
        registry = PluginRegistry(catalog, connections, settings)

        try:
            plugin = registry.get(item.target_platform, Publishable)
            result = await plugin.publish(item)
        except CapabilityNotSupported as exc:
            await _record_attempt(
                session, item, attempt_number, success=False, error=str(exc)
            )
            item.publish_error = str(exc)
            await session.commit()
            logger.error("publish.capability_not_supported", content_item_id=content_item_id)
            raise PublishAttemptFailed(str(exc)) from exc

        await _record_attempt(
            session,
            item,
            attempt_number,
            success=result.success,
            published_url=result.published_url,
            error=result.error,
        )

        if not result.success:
            item.publish_error = result.error
            session.add(
                AuditLog(
                    org_id=project.org_id,
                    actor_user_id=None,
                    action="content_item.publish_failed",
                    target=str(item.id),
                    metadata_={"error": result.error, "attempt_number": attempt_number},
                )
            )
            await session.commit()
            logger.warning(
                "publish.failed",
                content_item_id=content_item_id,
                attempt_number=attempt_number,
                error=result.error,
            )
            raise PublishAttemptFailed(result.error or "publish failed")

        item.status = ContentItemStatus.PUBLISHED
        item.published_at = datetime.now(UTC)
        item.publish_error = None
        await session.flush()

        await EventPublisher(session).publish(
            project_id=item.project_id,
            event_type="content_item.published",
            payload={
                "content_item_id": str(item.id),
                "target_platform": item.target_platform,
                "published_url": result.published_url,
            },
        )
        session.add(
            AuditLog(
                org_id=project.org_id,
                actor_user_id=None,
                action="content_item.published",
                target=str(item.id),
            )
        )
        await session.commit()
        logger.info(
            "publish.succeeded", content_item_id=content_item_id, attempt_number=attempt_number
        )


async def _record_attempt(
    session: AsyncSession,
    item: ContentItem,
    attempt_number: int,
    *,
    success: bool,
    published_url: str | None = None,
    error: str | None = None,
) -> None:
    session.add(
        ContentPublishAttempt(
            content_item_id=item.id,
            attempt_number=attempt_number,
            success=success,
            published_url=published_url,
            error=error,
        )
    )
    await session.flush()


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings

    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    ctx["plugin_catalog"] = catalog
    logger.info("worker_publish.started", plugins=[m.key for m in catalog.all()])


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [publish_content_item]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
