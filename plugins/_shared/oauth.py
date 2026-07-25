"""OAuth2 provider metadata a plugin declares — see docs/auth/OAUTH2_ARCHITECTURE.md and
docs/decisions/0011-generic-oauth2-plugin-framework.md.

A plugin with `auth_type="oauth2"` declares an `OAuthProviderSpec` on its manifest instead of
implementing any OAuth logic itself. The platform (`app/core/oauth/`) executes RFC 6749 (with
optional RFC 7636 PKCE) generically against whatever this spec describes — no plugin ever
builds an authorize URL, exchanges a code, or refreshes a token. This module stays
dependency-free, same as the rest of plugins/_shared: plain dataclasses, stdlib typing only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# "required": always send a PKCE code_challenge (the provider rejects requests without one).
# "supported": send one opportunistically — strictly additive security, no downside for a
#   provider that merely tolerates it.
# "unsupported": never send one — some providers reject requests carrying an unrecognized
#   param, so this must be an explicit, correct-per-provider declaration, not a guess.
PKCEPolicy = Literal["required", "supported", "unsupported"]

TokenEndpointAuthMethod = Literal["client_secret_basic", "client_secret_post"]


@dataclass(frozen=True, slots=True)
class OAuthProviderSpec:
    """See docs/auth/OAUTH2_ARCHITECTURE.md §1, §4. `scopes` are what this plugin requests;
    the connection's actual `granted_scopes` (recorded after the provider's callback) may
    differ if the user's account or the provider restricts what's granted.

    `extra_authorize_params`/`extra_token_params` exist because real providers deviate from
    bare RFC 6749 in small, provider-specific ways (e.g. Google requires
    `access_type=offline&prompt=consent` on the authorize call to receive a refresh token at
    all) — declared here, merged in generically by the platform's OAuthClient, so the
    platform never special-cases a specific provider's quirks in code.

    `extra_token_headers` exists for the same reason, one layer down: some providers require
    specific HTTP headers (not body params) on every API call, including the token endpoint
    itself — e.g. Reddit rejects requests with no descriptive `User-Agent`, a rule that
    applies to its token/refresh/revoke endpoints, not just its data API. Discovered
    implementing the Reddit plugin (`plugins/reddit/manifest.py`) against this framework —
    see docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md.
    """

    authorize_url: str
    token_url: str
    revoke_url: str | None = None
    scopes: tuple[str, ...] = ()
    pkce: PKCEPolicy = "unsupported"
    token_endpoint_auth_method: TokenEndpointAuthMethod = "client_secret_basic"
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    extra_token_params: dict[str, str] = field(default_factory=dict)
    extra_token_headers: dict[str, str] = field(default_factory=dict)


__all__ = ["OAuthProviderSpec", "PKCEPolicy", "TokenEndpointAuthMethod"]
