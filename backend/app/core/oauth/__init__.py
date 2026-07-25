"""Generic, provider-agnostic OAuth2 platform subsystem — see
docs/auth/OAUTH2_ARCHITECTURE.md and docs/decisions/0011-generic-oauth2-plugin-framework.md.

The only code in the system that makes HTTP calls to a plugin's declared
authorize_url/token_url/revoke_url, builds PKCE challenges, or issues/verifies OAuth state
tokens. No plugin, and no other part of the platform, duplicates any of this.
"""

from __future__ import annotations
