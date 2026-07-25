"""Envelope encryption for plugin credentials — see ADR 0010
(docs/decisions/0010-envelope-encryption-for-credentials.md) and docs/security/SECURITY.md.

A master key (derived from `Settings.credential_master_key`) never touches a credential
directly — it only wraps a unique, randomly generated **data key** per `plugin_connections`
row. The data key encrypts the actual credential material. AES-256-GCM for both layers: an
authenticated cipher, so tampering (or a wrong key) fails decryption loudly
(`cryptography.exceptions.InvalidTag`), never silently returns corrupt plaintext.

This is the first real implementation of the pattern ADR 0010 specified — `plugin_connections`
carried `credentials_encrypted`/`credential_data_key_wrapped` since Phase 1, but nothing wrote
to them until the OAuth2 framework (docs/auth/OAUTH2_ARCHITECTURE.md), its first consumer.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LENGTH = 12  # AES-GCM's standard nonce size (96 bits)


def derive_master_key(secret: str) -> bytes:
    """Reduces an arbitrary-length operator secret (`Settings.credential_master_key`) to
    exactly 32 bytes (AES-256) via SHA-256 — so operators set a normal `.env` string, not a
    base64-encoded key of a precise length. Deterministic: the same secret always derives the
    same key, which is what makes `CREDENTIAL_MASTER_KEY` in `.env` the actual key material,
    not just a seed that would need separate persistence."""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def generate_data_key() -> bytes:
    """A fresh, random 256-bit key — call once per `plugin_connections` row, never reused
    across rows."""
    return AESGCM.generate_key(256)


def _aead_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _aead_decrypt(key: bytes, blob: bytes) -> bytes:
    nonce, ciphertext = blob[:_NONCE_LENGTH], blob[_NONCE_LENGTH:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def envelope_encrypt(master_key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Returns `(ciphertext, wrapped_data_key)` — maps directly onto
    `plugin_connections.credentials_encrypted` / `credential_data_key_wrapped`. A fresh data
    key is generated on every call; encrypting the same plaintext twice produces different
    ciphertext (both the nonce and the data key differ)."""
    data_key = generate_data_key()
    ciphertext = _aead_encrypt(data_key, plaintext)
    wrapped_data_key = _aead_encrypt(master_key, data_key)
    return ciphertext, wrapped_data_key


def envelope_decrypt(master_key: bytes, ciphertext: bytes, wrapped_data_key: bytes) -> bytes:
    """Inverse of `envelope_encrypt`. Raises `cryptography.exceptions.InvalidTag` if either
    layer's authentication tag doesn't verify (wrong master key, or the ciphertext/wrapped key
    was tampered with) — never returns corrupt plaintext silently."""
    data_key = _aead_decrypt(master_key, wrapped_data_key)
    return _aead_decrypt(data_key, ciphertext)


def rewrap_data_key(old_master_key: bytes, new_master_key: bytes, wrapped_data_key: bytes) -> bytes:
    """Master-key rotation primitive — see docs/security/SECURITY.md's rotation runbook.
    Decrypts the data key under the old master key, re-encrypts (wraps) it under the new one.
    Never touches the credential ciphertext itself, which is what makes rotation cheap. Not
    wired into an operational rotation job/script by this change — see
    docs/reviews/OAUTH_IMPLEMENTATION_REPORT.md for why that's explicitly out of scope here."""
    data_key = _aead_decrypt(old_master_key, wrapped_data_key)
    return _aead_encrypt(new_master_key, data_key)


__all__ = [
    "InvalidTag",
    "derive_master_key",
    "envelope_decrypt",
    "envelope_encrypt",
    "generate_data_key",
    "rewrap_data_key",
]
