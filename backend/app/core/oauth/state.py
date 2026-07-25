"""Signed, stateless OAuth state token — see docs/auth/OAUTH2_ARCHITECTURE.md §3, §6.

Mirrors app/core/security.py's session-token pattern (itsdangerous, URLSafeTimedSerializer)
with a different payload and its own salt (so a session token and a state token, even if
somehow structurally similar, can never be swapped for each other). No server-side storage —
the signature is the CSRF guarantee; `max_age` bounds the window an intercepted-but-unused
state could be replayed in. See docs/auth/OAUTH2_ARCHITECTURE.md §6 for why this is stateless
by design, not a missing feature.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# 10 minutes — generous for a human to complete a provider's consent screen, tight enough to
# bound a leaked-state replay window. See docs/auth/OAUTH2_ARCHITECTURE.md §3.
STATE_MAX_AGE_SECONDS = 60 * 10


@dataclass(frozen=True, slots=True)
class OAuthState:
    project_id: uuid.UUID
    plugin_key: str
    label: str
    user_id: uuid.UUID
    # Present only when the plugin's OAuthProviderSpec.pkce is "required" or "supported" —
    # None for a provider that doesn't use PKCE.
    code_verifier: str | None
    nonce: str


def generate_nonce() -> str:
    return secrets.token_urlsafe(16)


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="growthos-oauth-state")


def create_state_token(state: OAuthState, *, secret_key: str) -> str:
    payload = {
        "project_id": str(state.project_id),
        "plugin_key": state.plugin_key,
        "label": state.label,
        "user_id": str(state.user_id),
        "code_verifier": state.code_verifier,
        "nonce": state.nonce,
    }
    return _serializer(secret_key).dumps(payload)


def verify_state_token(token: str, *, secret_key: str) -> OAuthState | None:
    """Returns the decoded state if the signature is valid and unexpired, else `None` — never
    raises, mirroring `verify_session_token`'s contract (an invalid/expired/tampered state is
    equivalent to "this OAuth callback isn't legitimate," not a 500)."""
    try:
        data = _serializer(secret_key).loads(token, max_age=STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return OAuthState(
            project_id=uuid.UUID(data["project_id"]),
            plugin_key=data["plugin_key"],
            label=data["label"],
            user_id=uuid.UUID(data["user_id"]),
            code_verifier=data["code_verifier"],
            nonce=data["nonce"],
        )
    except (KeyError, ValueError, TypeError):
        return None


__all__ = [
    "STATE_MAX_AGE_SECONDS",
    "OAuthState",
    "create_state_token",
    "generate_nonce",
    "verify_state_token",
]
