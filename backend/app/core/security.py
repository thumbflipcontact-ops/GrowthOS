"""Password hashing and session token signing — see docs/auth/AUTHENTICATION.md.

Argon2id for passwords, a signed (not encrypted — the payload is just a user id, not
sensitive) timed token for sessions, held in an HTTP-only cookie.

**CSRF cookie is generated but not yet verified anywhere** — see
docs/reviews/PRODUCTION_READINESS_REVIEW.md S2. `generate_csrf_token()` below is set
alongside the session cookie (app/api/v1/auth.py), intended as one half of a standard
double-submit pattern, but no dependency or middleware compares it against a request header
yet — this docstring previously (incorrectly) claimed it was "checked on state-changing
requests." In practice, `SameSite=Lax` on the session cookie mitigates the classic cross-site
form-POST case; the double-submit check itself remains a real gap, tracked but not
implemented in Phase 2D (medium severity, scoped out in favor of higher-severity findings —
see docs/reviews/PRODUCTION_HARDENING_REPORT.md).
"""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

if TYPE_CHECKING:
    from fastapi import Response

    from app.core.config import Settings

_hasher = PasswordHasher()

SESSION_COOKIE_NAME = "growthos_session"
CSRF_COOKIE_NAME = "growthos_csrf"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="growthos-session")


def create_session_token(user_id: uuid.UUID, *, secret_key: str) -> str:
    return _serializer(secret_key).dumps({"user_id": str(user_id)})


def verify_session_token(token: str, *, secret_key: str) -> uuid.UUID | None:
    """Returns the user id if the token is valid and unexpired, else None. Never raises —
    an invalid/expired/tampered session token is equivalent to "not logged in", not a 500."""
    try:
        data = _serializer(secret_key).loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return uuid.UUID(data["user_id"])
    except (KeyError, ValueError, TypeError):
        return None


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def cookie_security_attrs(settings: Settings) -> dict[str, object]:
    """Shared by every call site that sets or clears SESSION_COOKIE_NAME / CSRF_COOKIE_NAME
    (password login/register, Google login — app/api/v1/auth_oauth.py) — moved here from
    app/api/v1/auth.py so a second call site never risks drifting out of sync with these
    exact attributes. SameSite=Lax only survives cross-origin fetch when frontend and backend
    share a registrable domain (e.g. app.example.com + api.example.com — see
    frontend_origin's docstring in app/core/config.py). The default Railway/Vercel domains
    (*.up.railway.app vs *.vercel.app) do NOT share one — they're genuinely cross-site, and
    SameSite=Lax cookies are dropped by the browser on cross-site fetch/XHR. SameSite=None
    (requires Secure, which is_secure already guarantees outside local dev) is the correct
    setting for that deployment shape. This does not newly weaken CSRF defenses — the
    double-submit check itself is a pre-existing, separately-tracked gap (see
    docs/reviews/PRODUCTION_READINESS_REVIEW.md S2); SameSite=Lax was never a complete
    defense on its own, and closing S2 for real matters more once this is None.

    A delete_cookie() with mismatched secure/samesite produces a Set-Cookie header the
    browser silently drops in a cross-site context (it never overwrites the original
    SameSite=None; Secure cookie) — logout() hit exactly this bug once: it looked like it
    worked (204 response, frontend redirected to /login) but the real session cookie was
    never actually cleared, so the user stayed logged in. Every caller must use these exact
    same attributes for both setting AND clearing."""
    is_secure = not settings.is_local
    same_site = "none" if not settings.is_local else "lax"
    return {"secure": is_secure, "samesite": same_site}


def set_session_cookies(response: Response, user_id: str, settings: Settings) -> None:
    cookie_attrs = cookie_security_attrs(settings)
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
