"""Typed, already-decrypted credential shapes a plugin receives at construction time — see
docs/auth/OAUTH2_ARCHITECTURE.md §1, §4.

A plugin never sees `plugin_connections.credentials_encrypted` (ciphertext) or performs any
decryption itself — the registry (`app/core/plugin_registry.py`) decrypts (the documented
boundary, per docs/security/SECURITY.md: "decryption happens only inside plugin instance
construction") and hands the plugin one of these instead, via `ResolvedConnection.credentials`
(see `plugins/_shared/base.py`). Dependency-free: plain dataclasses, stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class OAuth2Credentials:
    """What an `auth_type="oauth2"` plugin receives. `expires_at` and `granted_scopes` mirror
    `plugin_connections.token_expires_at`/`granted_scopes` (plaintext columns, not part of the
    encrypted envelope — see docs/auth/OAUTH2_ARCHITECTURE.md §2) — a plugin can check
    `expires_at` defensively, but is never responsible for refreshing: that's the platform's
    background job (`app/jobs/oauth_refresh.py`), never plugin code."""

    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime
    granted_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApiKeyCredentials:
    """What an `auth_type="api_key"` plugin receives."""

    api_key: str


Credentials = OAuth2Credentials | ApiKeyCredentials

__all__ = ["ApiKeyCredentials", "Credentials", "OAuth2Credentials"]
