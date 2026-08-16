"""See app/core/webhooks/signing.py."""

from __future__ import annotations

import hashlib
import hmac

from app.core.webhooks.signing import sign_payload


def test_sign_payload_matches_manual_hmac() -> None:
    secret = "s3cr3t"
    body = b'{"event":"conversation.discovered"}'
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert sign_payload(secret, body) == expected


def test_sign_payload_differs_for_different_secrets() -> None:
    body = b"same body"
    assert sign_payload("secret-a", body) != sign_payload("secret-b", body)


def test_sign_payload_differs_for_different_bodies() -> None:
    secret = "same-secret"
    assert sign_payload(secret, b"body-a") != sign_payload(secret, b"body-b")
