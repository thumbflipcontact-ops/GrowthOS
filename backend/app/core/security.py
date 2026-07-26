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

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

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
