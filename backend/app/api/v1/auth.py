"""Auth endpoints — the "Authentication scaffold" foundation piece.
See docs/auth/AUTHENTICATION.md.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    get_login_account_limiter,
    get_login_ip_limiter,
    get_password_reset_account_limiter,
    get_password_reset_ip_limiter,
    get_register_global_limiter,
    get_register_ip_limiter,
    get_resend_verification_account_limiter,
    get_resend_verification_ip_limiter,
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
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    OrganizationResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth_service import AuthService
from app.services.email_verification_service import EmailVerificationService
from app.services.password_reset_service import PasswordResetService

logger = structlog.get_logger()

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
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_register_ip_limiter),
    global_limiter: RateLimiter = Depends(get_register_global_limiter),
) -> User:
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many signups from this address. Try again shortly.")
    # Backstops the per-IP check above against a bot swarm spread across many addresses — see
    # get_register_global_limiter's docstring. Checked second, after the cheaper per-IP check,
    # so a single noisy IP burns its own budget first rather than eating into everyone else's.
    if not global_limiter.try_acquire("global"):
        raise TooManyRequests("Too many signups right now. Try again shortly.")

    if body.website:
        # Honeypot tripped — see RegisterRequest.website's docstring. Fabricated, never
        # persisted: no organization/user row, no verification email sent, nothing for a
        # retry to build on. Shaped exactly like a real success response so a scripted caller
        # has no signal that anything was different.
        #
        # Logged server-side only (never returned to the caller, never persisted to the
        # database) so an operator can tell real signups from bot noise after the fact — a
        # plausible-looking name/email and a normal browser user_agent suggests a real
        # person's autofill caught this hidden field, not a bot; a garbled name/email or a
        # scripted-looking user_agent (curl, python-requests, headless-*) suggests the
        # opposite. Not a definitive classifier either way, just the same signal a human
        # would eyeball to make that call.
        logger.warning(
            "auth.register_honeypot_tripped",
            email=body.email,
            name=body.name,
            ip=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
        return UserResponse(id=uuid.uuid4(), email=body.email, name=body.name)  # type: ignore[return-value]

    service = AuthService(session)
    user = await service.register(
        org_name=body.org_name,
        org_slug=body.org_slug,
        email=body.email,
        name=body.name,
        password=body.password,
    )
    # No session cookie yet — granted once /auth/verify-email confirms this is a real,
    # reachable address. A registration response the caller can't log in with looks odd in
    # isolation, but it's the whole point: an account that never verifies never gets in.
    await EmailVerificationService(session, settings).send_verification_email(user=user)
    return user


@router.post("/verify-email", response_model=UserResponse)
async def verify_email(
    body: VerifyEmailRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    service = EmailVerificationService(session, settings)
    user = await service.verify(token=body.token)
    # Same as reset-password: a freshly-verified account shouldn't require a second trip
    # through login.
    _set_session_cookies(response, str(user.id), settings)
    return user


@router.post("/resend-verification", status_code=204, response_model=None)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_resend_verification_ip_limiter),
    account_limiter: RateLimiter = Depends(get_resend_verification_account_limiter),
) -> None:
    # Same rate-limit-before-any-work shape as /forgot-password, and the same non-enumeration
    # rule: always 204, whether or not the email has an account or is already verified — see
    # EmailVerificationService.resend.
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many attempts from this address. Try again shortly.")
    if not account_limiter.try_acquire(f"account:{body.email}"):
        raise TooManyRequests("Too many attempts for this account. Try again shortly.")

    service = EmailVerificationService(session, settings)
    await service.resend(email=body.email)


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


@router.post("/forgot-password", status_code=204, response_model=None)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_password_reset_ip_limiter),
    account_limiter: RateLimiter = Depends(get_password_reset_account_limiter),
) -> None:
    # Same rate-limit-before-any-work shape as /login, and the same non-enumeration rule as
    # AuthService.authenticate(): this always returns 204, whether or not the email has an
    # account, so the response itself can never be used to check who's registered.
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many attempts from this address. Try again shortly.")
    if not account_limiter.try_acquire(f"account:{body.email}"):
        raise TooManyRequests("Too many attempts for this account. Try again shortly.")

    service = PasswordResetService(session, settings)
    await service.request_reset(email=body.email)


@router.post("/reset-password", response_model=UserResponse)
async def reset_password(
    body: ResetPasswordRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> User:
    service = PasswordResetService(session, settings)
    user = await service.reset_password(token=body.token, new_password=body.new_password)
    # Same as register: a freshly-set password shouldn't require a second trip through login.
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
