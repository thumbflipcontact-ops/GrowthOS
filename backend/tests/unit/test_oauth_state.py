"""See docs/auth/OAUTH2_ARCHITECTURE.md §3, §6 and app/core/oauth/state.py."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.core.oauth.state import OAuthState, create_state_token, generate_nonce, verify_state_token

_SECRET = "test-secret-key"


def _state(**overrides: object) -> OAuthState:
    defaults: dict = {
        "project_id": uuid.uuid4(),
        "plugin_key": "reddit",
        "label": "default",
        "user_id": uuid.uuid4(),
        "code_verifier": None,
        "nonce": generate_nonce(),
    }
    defaults.update(overrides)
    return OAuthState(**defaults)


def test_round_trip() -> None:
    state = _state()
    token = create_state_token(state, secret_key=_SECRET)
    decoded = verify_state_token(token, secret_key=_SECRET)
    assert decoded == state


def test_round_trip_with_pkce_verifier() -> None:
    state = _state(code_verifier="a-code-verifier")
    token = create_state_token(state, secret_key=_SECRET)
    decoded = verify_state_token(token, secret_key=_SECRET)
    assert decoded is not None
    assert decoded.code_verifier == "a-code-verifier"


def test_rejects_wrong_secret_key() -> None:
    token = create_state_token(_state(), secret_key="secret-a")
    assert verify_state_token(token, secret_key="secret-b") is None


def test_rejects_tampered_token() -> None:
    # Flips a character in the middle of the whole token rather than assuming a specific
    # dot-separated-segment shape — itsdangerous prefixes a "." marker when it compresses a
    # large-enough payload (this state payload, several UUIDs plus a nonce, is compressed),
    # which makes assumptions about "the payload segment" fragile. See
    # backend/tests/unit/test_security.py's session-token equivalent for the narrower
    # last-character/padding pitfall this sidesteps too.
    token = create_state_token(_state(), secret_key=_SECRET)
    mid = len(token) // 2
    flipped = "A" if token[mid] != "A" else "B"
    tampered = token[:mid] + flipped + token[mid + 1 :]
    assert verify_state_token(tampered, secret_key=_SECRET) is None


def test_rejects_expired_token() -> None:
    token = create_state_token(_state(), secret_key=_SECRET)
    with patch("app.core.oauth.state.STATE_MAX_AGE_SECONDS", -1):
        assert verify_state_token(token, secret_key=_SECRET) is None


def test_rejects_garbage_input() -> None:
    assert verify_state_token("not-a-real-token", secret_key=_SECRET) is None


def test_nonce_is_random() -> None:
    assert generate_nonce() != generate_nonce()
