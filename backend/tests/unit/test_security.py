"""See docs/auth/AUTHENTICATION.md."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.core.security import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)


def test_password_hash_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_password_hash_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_password_hash_is_not_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_session_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, secret_key="secret")
    assert verify_session_token(token, secret_key="secret") == user_id


def test_session_token_rejects_wrong_secret() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, secret_key="secret-a")
    assert verify_session_token(token, secret_key="secret-b") is None


def test_session_token_rejects_tampered_payload() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, secret_key="secret")
    # itsdangerous tokens are `payload.timestamp.signature` (dot-separated base64url
    # segments). Flipping a character in the MIDDLE of the payload segment is the reliable
    # way to force a byte-level change — flipping the token's trailing character is not:
    # base64's last character in a block can encode padding bits a single flip doesn't
    # always disturb, which made this test flaky (it passed most runs, failed some).
    payload_segment, sep, rest = token.partition(".")
    mid = len(payload_segment) // 2
    flipped_char = "A" if payload_segment[mid] != "A" else "B"
    tampered_payload = payload_segment[:mid] + flipped_char + payload_segment[mid + 1 :]
    tampered = tampered_payload + sep + rest
    assert verify_session_token(tampered, secret_key="secret") is None


def test_session_token_rejects_expired_token() -> None:
    user_id = uuid.uuid4()
    token = create_session_token(user_id, secret_key="secret")
    with patch("app.core.security.SESSION_MAX_AGE_SECONDS", -1):
        assert verify_session_token(token, secret_key="secret") is None
