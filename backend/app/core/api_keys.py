"""Public-API key generation and hashing — see app/api/deps.py's require_api_key_project,
the only place a key is ever verified.

SHA-256, not Argon2 (unlike password hashing, app/core/security.py) — the token itself carries
256 bits of secrets.token_urlsafe entropy, unlike a human-chosen password, so a fast
deterministic hash is correct here: it's what lets a lookup be a single indexed equality query
rather than a linear argon2.verify() scan over every live key. Mirrors how GitHub/Stripe hash
API tokens, not this codebase's own password-hashing convention.
"""

from __future__ import annotations

import hashlib
import secrets

_TOKEN_PREFIX = "thr_"


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_token, key_hash, key_prefix). full_token is shown to the caller exactly
    once, at creation — only key_hash is ever persisted. key_prefix (the first 12 characters
    of the full token) is stored unhashed purely so a dashboard list view can show "which key
    is this" without ever being able to reconstruct or re-display the full secret."""
    full_token = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return full_token, hash_api_key(full_token), full_token[:12]


def hash_api_key(token: str) -> str:
    """Verification is a hashed-value equality lookup in the database (an indexed WHERE
    key_hash = :hash), not an application-level comparison of the raw secret — so there's no
    Python-level timing side-channel to guard with hmac.compare_digest here, unlike comparing
    two raw strings directly in app code."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_api_key(value: str) -> bool:
    """Cheap prefix check before a DB round trip — not a security boundary itself."""
    return value.startswith(_TOKEN_PREFIX)


__all__ = ["generate_api_key", "hash_api_key", "looks_like_api_key"]
