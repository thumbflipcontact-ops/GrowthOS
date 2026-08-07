"""Auth endpoints — the "Authentication scaffold" foundation piece.
See docs/auth/AUTHENTICATION.md.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_login_account_limiter,
    get_login_ip_limiter,
    get_settings_dep,
)
from app.core.config import Settings
from app.core.errors import TooManyRequests
from app.core.rate_limit import RateLimiter
from app.core.security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    generate_csrf_token,
)
from app.models.identity import Organization, User
from app.repositories.user_repository import MembershipRepository
from app.schemas.auth import LoginRequest, OrganizationResponse, RegisterRequest, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_security_attrs(settings: Settings) -> dict[str, object]:
    # SameSite=Lax only survives cross-origin fetch when frontend and backend share a
    # registrable domain (e.g. app.example.com + api.example.com — see
    # frontend_origin's docstring in app/core/config.py). The default Railway/Vercel domains
    # (*.up.railway.app vs *.vercel.app) do NOT share one — they're genuinely cross-site, and
    # SameSite=Lax cookies are dropped by the browser on cross-site fetch/XHR. SameSite=None
    # (requires Secure, which is_secure already guarantees outside local dev) is the correct
    # setting for that deployment shape. This does not newly weaken CSRF defenses — the
    # double-submit check itself is a pre-existing, separately-tracked gap (see
    # docs/reviews/PRODUCTION_READINESS_REVIEW.md S2); SameSite=Lax was never a complete
    # defense on its own, and closing S2 for real matters more once this is None.
    #
    # Every call that sets OR clears SESSION_COOKIE_NAME / CSRF_COOKIE_NAME must use these
    # exact same attributes. A delete_cookie() with mismatched secure/samesite produces a
    # Set-Cookie header the browser silently drops in a cross-site context (it never overwrites
    # the original SameSite=None; Secure cookie) — logout() hit exactly this bug: it looked
    # like it worked (204 response, frontend redirected to /login) but the real session cookie
    # was never actually cleared, so the user stayed logged in.
    is_secure = not settings.is_local
    same_site = "none" if not settings.is_local else "lax"
    return {"secure": is_secure, "samesite": same_site}


def _set_session_cookies(response: Response, user_id: str, settings: Settings) -> None:
    cookie_attrs = _cookie_security_attrs(settings)
    session_token = create_session_token(
        uuid.UUID(user_id), secret_key=settings.secret_key.get_secret_value()
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        **cookie_attrs,
    )
    # CSRF cookie is intentionally NOT httponly — the frontend reads it and echoes it back
    # in a request header on state-changing requests (double-submit pattern), see
    # docs/auth/AUTHENTICATION.md.
    response.set_cookie(
        CSRF_COOKIE_NAME,
        generate_csrf_token(),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
        **cookie_attrs,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    service = AuthService(session)
    user = await service.register(
        org_name=body.org_name,
        org_slug=body.org_slug,
        email=body.email,
        name=body.name,
        password=body.password,
    )
    _set_session_cookies(response, str(user.id), settings)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_login_ip_limiter),
    account_limiter: RateLimiter = Depends(get_login_account_limiter),
) -> User:
    # Both per-source-IP (volumetric abuse) and per-account (distributed credential-stuffing
    # against one target) must independently allow the attempt — see
    # docs/reviews/PRODUCTION_READINESS_REVIEW.md S1. Checked before any password work so a
    # locked-out caller never even reaches the (deliberately slow) Argon2id verify.
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many login attempts from this address. Try again shortly.")
    if not account_limiter.try_acquire(f"account:{body.email.lower()}"):
        raise TooManyRequests("Too many login attempts for this account. Try again shortly.")

    service = AuthService(session)
    user = await service.authenticate(email=body.email, password=body.password)
    _set_session_cookies(response, str(user.id), settings)
    return user


@router.post("/logout", status_code=204, response_model=None)
async def logout(response: Response, settings: Settings = Depends(get_settings_dep)) -> None:
    cookie_attrs = _cookie_security_attrs(settings)
    response.delete_cookie(SESSION_COOKIE_NAME, **cookie_attrs)
    response.delete_cookie(CSRF_COOKIE_NAME, **cookie_attrs)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/me/organizations", response_model=list[OrganizationResponse])
async def my_organizations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Organization]:
    """The orgs this user belongs to — needed by the frontend right after login/register,
    since `/auth/register`'s response (UserResponse) deliberately carries no org data (a user
    can, in principle, belong to more than one org even though registration only ever creates
    membership in the one it bootstraps)."""
    memberships = await MembershipRepository(session).list_for_user(current_user.id)
    organizations = []
    for membership in memberships:
        organization = await session.get(Organization, membership.org_id)
        if organization is not None:
            organizations.append(organization)
    return organizations
