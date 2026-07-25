"""The publish-jobs Arq worker. See docs/jobs/BACKGROUND_JOBS.md and ARCHITECTURE.md §8.

`publish_content_item`'s body is a placeholder in Phase 1 — the real implementation calls
the owning plugin's `Publishable.publish()` for a `content_item` already in `approved`, and
is the *only* call site in the codebase allowed to do so (ARCHITECTURE.md §8). That's tied to
`ContentApprovalService`, explicitly out of Phase 1 scope as business logic (see
ROADMAP.md). This exists so the queue plumbing — enqueued on approval, idempotency-keyed by
`content_item.id` so a duplicate enqueue is a no-op — is real and tested; Phase 2 replaces
the body with a real plugin `publish()` call.
"""

from __future__ import annotations

import structlog
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory

logger = structlog.get_logger()


async def publish_content_item(ctx: dict, content_item_id: str) -> None:
    logger.info("publish.placeholder", content_item_id=content_item_id)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)


async def shutdown(ctx: dict) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [publish_content_item]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
