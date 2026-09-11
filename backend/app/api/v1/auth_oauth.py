"""Google "Continue with Google" login/signup routes — see
app/services/google_oauth_service.py.

Kept separate from app/api/v1/auth.py (same `/auth` prefix, its own router/file) since this
is a materially different concern — an external identity provider, not password auth — and
from app/api/v1/oauth.py (the plugin-connection OAuth callback), which requires
`get_current_user` and can never serve login: establishing the session IS the point here.

Both routes communicate outcome by redirecting the browser (a top-level navigation from
Google's own redirect, never a frontend fetch() call), matching app/api/v1/oauth.py's own
"never a raw JSON error body a user would see rendered as text" reasoning — success lands on
Settings.oauth_frontend_redirect_url (today, /dashboard, which already redirects a
first-time visitor into /onboarding on its own — see frontend/app/dashboard/page.tsx),
failure lands on the login page with an `?error=` the frontend shows as a banner.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_google_oauth_ip_limiter, get_settings_dep
from app.core.config import Settings
from app.core.errors import GrowthOSError, TooManyRequests
from app.core.rate_limit import RateLimiter
from app.core.security import set_session_cookies
from app.services.google_oauth_service import GoogleOAuthService, build_google_authorize_url

router = APIRouter(prefix="/auth/google", tags=["auth-oauth"])


@router.get("/start")
async def google_start(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_google_oauth_ip_limiter),
) -> RedirectResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many attempts from this address. Try again shortly.")

    return RedirectResponse(build_google_authorize_url(settings), status_code=302)


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ip_limiter: RateLimiter = Depends(get_google_oauth_ip_limiter),
) -> RedirectResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not ip_limiter.try_acquire(f"ip:{client_ip}"):
        raise TooManyRequests("Too many attempts from this address. Try again shortly.")

    login_url = settings.frontend_origin.rstrip("/") + "/login"
    if error is not None or code is None or state is None:
        # The user denied consent on Google's own screen, or Google sent back something this
        # route can't use — either way there's no code to exchange.
        query = urlencode({"error": "google_oauth_failed"})
        return RedirectResponse(f"{login_url}?{query}", status_code=302)

    service = GoogleOAuthService(session, settings)
    try:
        user = await service.handle_callback(code=code, state_token=state)
    except GrowthOSError:
        query = urlencode({"error": "google_oauth_failed"})
        return RedirectResponse(f"{login_url}?{query}", status_code=302)

    response = RedirectResponse(settings.oauth_frontend_redirect_url, status_code=302)
    set_session_cookies(response, str(user.id), settings)
    return response
