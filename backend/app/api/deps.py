"""FastAPI dependency providers — the "Dependency injection" foundation piece.

Every route handler gets the database session, the current user, and (for project-scoped
routes) verified project access exclusively through these dependencies — never by
constructing a session or checking membership inline. See
docs/auth/AUTHENTICATION.md's `require_project_access` note and ARCHITECTURE.md §2.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from arq import ArqRedis, create_pool
from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.entitlements import require_org_entitled
from app.core.errors import AuthenticationError, AuthorizationError, NotFoundError
from app.core.plugin_catalog import PluginCatalog
from app.core.rate_limit import RateLimiter
from app.core.redis import build_redis_settings
from app.core.security import SESSION_COOKIE_NAME, verify_session_token
from app.models.identity import Organization, User
from app.models.project import Project
from app.repositories.user_repository import MembershipRepository, UserRepository

# Process-local, in-memory login rate limiters — see app/core/rate_limit.py and
# docs/reviews/PRODUCTION_READINESS_REVIEW.md S1. Module-level singletons (one process = one
# set of buckets), exposed as overridable dependencies (like get_arq_redis below) so tests can
# substitute a small-capacity instance without affecting every other test that happens to hit
# POST /auth/login as setup.
_login_ip_limiter = RateLimiter(capacity=10, refill_rate=10 / 300)  # 10 attempts / 5 min / IP
# 5 attempts / 15 min / account
_login_account_limiter = RateLimiter(capacity=5, refill_rate=5 / 900)


def get_login_ip_limiter() -> RateLimiter:
    return _login_ip_limiter


def get_login_account_limiter() -> RateLimiter:
    return _login_account_limiter


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Request-scoped session — commits on a clean response, rolls back on any exception.
    See app/core/db.py for the underlying session_factory, created once at startup
    (app/main.py) and stored on app.state."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings_dep() -> Settings:
    return get_settings()


def get_plugin_catalog(request: Request) -> PluginCatalog:
    """The process-wide catalog built at startup (app/main.py's lifespan) — read-only from
    a request handler's perspective. See app/core/plugin_catalog.py."""
    catalog: PluginCatalog = request.app.state.plugin_catalog
    return catalog


async def get_arq_redis(request: Request) -> ArqRedis:
    """Lazily creates and caches one Arq connection pool per process, on first use — not at
    app startup (unlike `plugin_catalog` above), so a route that never enqueues a job (i.e.
    every route except `.../agent-configs/{agent_key}/runs/trigger`) imposes no live-Redis
    dependency. This is what lets `app.router.lifespan_context` keep running for free against
    a real Postgres in tests without also requiring a real Redis — see
    docs/jobs/BACKGROUND_JOBS.md and the trigger endpoint's own tests, which override this
    dependency instead of talking to a real broker."""
    pool = getattr(request.app.state, "arq_redis", None)
    if pool is None:
        settings = get_settings()
        pool = await create_pool(build_redis_settings(settings))
        request.app.state.arq_redis = pool
    return pool


async def get_current_user(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User:
    """Resolves the authenticated user from the signed session cookie. Raises
    AuthenticationError (401) if there is no session, the token is invalid/expired, or the
    user no longer exists — never returns None, so route handlers can rely on always having
    a real User once this dependency resolves. See docs/auth/AUTHENTICATION.md."""
    if session_token is None:
        raise AuthenticationError("Not authenticated.")

    user_id = verify_session_token(session_token, secret_key=settings.secret_key.get_secret_value())
    if user_id is None:
        raise AuthenticationError("Session is invalid or has expired.")

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise AuthenticationError("Session refers to a user that no longer exists.")
    return user


async def require_project_access(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    """The single place project-scoped authorization is enforced — every project-scoped
    route depends on this rather than checking membership inline. See
    docs/auth/AUTHENTICATION.md: "one FastAPI dependency ... used by every project-scoped
    route — one place to get this right, not one per endpoint." Raises NotFoundError if the
    project doesn't exist, AuthorizationError if the user isn't a member of its org — the
    project's existence is not leaked to a user who can't see it (both cases could arguably
    be 404s; we use 403 here because it's more actionable for a user who mistyped a URL
    while logged into the wrong org). Now that Phase 4 (docs/billing/BILLING_ARCHITECTURE.md)
    means genuine strangers hold accounts, the 403-vs-404 choice is a real tenant-isolation
    question, not a moot one — flagged as a fast-follow audit item there rather than changed
    here without evidence either choice actually matters at this project's UUID-keyed,
    unguessable-id scale. See docs/security/SECURITY.md."""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")

    membership = await MembershipRepository(session).get_by_org_and_user(
        project.org_id, current_user.id
    )
    if membership is None:
        raise AuthorizationError("You do not have access to this project.")

    return project


async def require_org_access(
    org_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    """The org-scoped counterpart to require_project_access — used by routes that operate
    above the project level (e.g. listing/creating projects within an org)."""
    organization = await session.get(Organization, org_id)
    if organization is None:
        raise NotFoundError("Organization not found.")

    membership = await MembershipRepository(session).get_by_org_and_user(org_id, current_user.id)
    if membership is None:
        raise AuthorizationError("You do not have access to this organization.")

    return organization


async def require_active_subscription(
    project: Project = Depends(require_project_access),
    session: AsyncSession = Depends(get_db),
) -> Project:
    """Gates any route that would spend paid, metered plugin capacity (creating an OAuth
    connection, triggering an agent run) behind an active subscription or trial — see
    docs/billing/BILLING_ARCHITECTURE.md and app/core/entitlements.py. Deliberately layered
    on top of require_project_access rather than replacing it: this always checks
    membership first (a stranger gets 403, not 402, for a project they can't see at all),
    then billing status for a project they're actually a member of. Raises
    SubscriptionRequiredError (402) — the background-job equivalent
    (app/jobs/agent_runs.py, app/jobs/events.py, app/jobs/publish.py) calls
    `is_org_entitled` directly instead, since a job has no HTTP response to raise into."""
    await require_org_entitled(session, project.org_id)
    return project
