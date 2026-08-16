"""HMAC signing for outbound webhook payloads — see app/core/webhooks/dispatcher.py, the only
caller. Mirrors app/core/oauth/pkce.py's shape: a small pure function, no state.
"""

from __future__ import annotations

import hashlib
import hmac


def sign_payload(secret: str, body: bytes) -> str:
    """Hex HMAC-SHA256 of `body` keyed by the subscription's own secret — sent as
    X-Threadly-Signature so the receiver can verify the payload actually came from Threadly
    and wasn't tampered with in transit."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


__all__ = ["sign_payload"]
