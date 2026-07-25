"""FastAPI dependency providers — the "Dependency injection" foundation piece.

Every route handler gets the database session, the current user, and (for project-scoped
routes) verified project access exclusively through these dependencies — never by
constructing a session or checking membership inline. See
docs/auth/AUTHENTICATION.md's `require_project_access` note and ARCHITECTURE.md §2.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, AuthorizationError, NotFoundError
from app.core.security import SESSION_COOKIE_NAME, verify_session_token
from app.models.identity import Organization, User
from app.models.project import Project
from app.repositories.user_repository import MembershipRepository, UserRepository


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
    while logged into the wrong org, and this is a single-operator v1 system, not a
    multi-tenant one where existence-leakage is a live threat — see
    docs/security/SECURITY.md)."""
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
