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
attempt leaves `content_items.status` at `approved` with `publish_error` set and raises
`arq.worker.Retry` so Arq's own retry/backoff policy (`WorkerSettings.max_tries` below)
actually applies (see docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1 —
`app/core/job_retry.py`'s docstring explains why a plain exception here would not have
retried at all); after the final retry is exhausted, the item stays
`approved`+`publish_error`-populated — visible via the API for a human to trigger a manual
retry (`POST .../content-items/{id}/retry-publish`), never silently dropped and never
auto-transitioned to any other status by a failure.

Before ever calling a plugin, this job also checks for a prior *successful* attempt already
recorded for this item (see `_prior_successful_attempt` below) — closing
docs/reviews/PRODUCTION_READINESS_REVIEW.md's R2: if a worker process crashes between a
plugin call succeeding (a real, external, irreversible Reddit post) and the transaction that
records that success committing, a naive re-run would call the plugin a second time and post
a duplicate comment. Finding a prior successful attempt means "this already posted, we just
never got to record the item's own status" — the job reconciles the item to `published` using
that attempt's own recorded URL, instead of posting again.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import RedisSettings
from arq.worker import Retry
from plugins._shared.base import Publishable
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.entitlements import is_org_entitled
from app.core.errors import CapabilityNotSupported
from app.core.events import EventPublisher
from app.core.job_retry import retry_backoff_seconds
from app.core.migration_check import verify_database_is_migrated
from app.core.observability import capture_exception, init_error_tracking
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.core.plugin_registry import PluginRegistry
from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus, ContentPublishAttempt
from app.models.project import Project
from app.repositories.content_repository import ContentPublishAttemptRepository
from app.repositories.plugin_repository import PluginConnectionRepository

logger = structlog.get_logger()


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

        # Cost-safety gate: a human already approved this item, but if the org's
        # subscription lapsed between approval and this job running, don't spend another
        # real, metered plugin API call on their behalf. Left `approved` with a clear
        # publish_error rather than raised as Retry — retrying won't help until they
        # resubscribe, so there's nothing for Arq's backoff to usefully wait for. See
        # docs/billing/BILLING_ARCHITECTURE.md.
        if not await is_org_entitled(session, project.org_id):
            item.publish_error = (
                "This organization's subscription is not active — publishing is paused "
                "until it's reactivated."
            )
            await session.commit()
            logger.info(
                "publish.skipped_org_not_entitled",
                content_item_id=content_item_id,
                org_id=str(project.org_id),
            )
            return

        attempts = ContentPublishAttemptRepository(session)
        existing_attempts = await attempts.list_by_content_item(item.id)

        prior_success = next((a for a in existing_attempts if a.success), None)
        if prior_success is not None:
            # See module docstring (R2): a crash between a plugin call succeeding and the
            # commit that would have recorded it can leave the item `approved` even though it
            # already posted. Reconcile using the prior attempt's own record instead of
            # calling the plugin again — never post the same content twice.
            logger.warning(
                "publish.recovered_from_prior_successful_attempt",
                content_item_id=content_item_id,
                attempt_number=prior_success.attempt_number,
            )
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
                    "published_url": prior_success.published_url,
                },
            )
            session.add(
                AuditLog(
                    org_id=project.org_id,
                    actor_user_id=None,
                    action="content_item.published",
                    target=str(item.id),
                    metadata_={"recovered_from_attempt": prior_success.attempt_number},
                )
            )
            await session.commit()
            return

        attempt_number = len(existing_attempts) + 1

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
            capture_exception(exc)
            raise Retry(defer=retry_backoff_seconds(ctx.get("job_try", 1))) from exc

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
            capture_exception(RuntimeError(f"publish failed: {result.error or 'unknown error'}"))
            raise Retry(defer=retry_backoff_seconds(ctx.get("job_try", 1)))

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
    init_error_tracking(settings, process_name="worker-publish")

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    await verify_database_is_migrated(engine)
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
    # See app/jobs/agent_runs.py's queue_name docstring — every enqueue_job call targeting
    # this worker must pass the matching _queue_name="publish" (app/api/v1/content_items.py).
    queue_name = "publish"
    functions = [publish_content_item]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
