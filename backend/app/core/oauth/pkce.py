"""RFC 7636 PKCE (Proof Key for Code Exchange) — see docs/auth/OAUTH2_ARCHITECTURE.md §6.

Only the S256 challenge method is supported (RFC 7636 §4.2's "plain" method is a weaker
fallback most providers don't require, and this platform doesn't offer it).
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    """A random string in RFC 7636 §4.1's required range (43–128 characters, unreserved
    charset). `secrets.token_urlsafe(64)` produces ~86 URL-safe characters — squarely inside
    the range, using a subset of the RFC's allowed alphabet."""
    return secrets.token_urlsafe(64)


def code_challenge_from_verifier(code_verifier: str) -> str:
    """`BASE64URL-ENCODE(SHA256(code_verifier))`, unpadded — RFC 7636 §4.2's S256 method."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


__all__ = ["code_challenge_from_verifier", "generate_code_verifier"]
