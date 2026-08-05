"""LinkedIn — publishable (not searchable — see README §"Why no search()") via LinkedIn's
OAuth2 flow. See docs/plugins/PLUGIN_ARCHITECTURE.md, docs/auth/OAUTH2_ARCHITECTURE.md, and
plugins/linkedin/README.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from plugins._shared.manifest import ContentTypeSpec, PluginManifest
from plugins._shared.oauth import OAuthProviderSpec


class LinkedInConnectionConfig(BaseModel):
    """LinkedIn's Posts API accepts a per-post visibility level; there is no Reddit-style
    scoping config to make here since this plugin has no search() to scope (see
    README §"Why no search()")."""

    visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"


MANIFEST = PluginManifest(
    key="linkedin",
    interface_version="1.0",
    # Deliberately NOT "searchable" — LinkedIn's public API surface has no general-purpose
    # content-search endpoint available to a standard app registration (the old Company/
    # Content Search APIs were locked to certified partners years ago). Declaring
    # "searchable" without a real search() to back it would fail
    # plugins/_shared/tests/test_plugin_contract.py's capability check, and more importantly
    # would violate CONTRIBUTING.md's "don't declare a capability you haven't implemented and
    # tested" — see README §"Why no search()" for the full reasoning.
    capabilities=("publishable",),
    content_types=(
        # 3000 is LinkedIn's documented character limit for an organic post's commentary
        # text. Unlike Reddit/Twitter, this hasn't been empirically verified against a real
        # account yet — see README §"Known constraints".
        ContentTypeSpec(key="linkedin_post", max_length=3_000, publish_target="post"),
    ),
    config_schema=LinkedInConnectionConfig,
    auth_type="oauth2",
    oauth=OAuthProviderSpec(
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        # LinkedIn has no publicly documented token-revocation endpoint for third-party apps
        # (unlike Reddit/X) — left None, which app/core/oauth/client.py's revoke() already
        # handles: it returns immediately without an HTTP call, and disconnection still
        # proceeds locally regardless (docs/auth/OAUTH2_ARCHITECTURE.md §6).
        revoke_url=None,
        # openid+profile back the OIDC /v2/userinfo call health_check() and publish() both
        # use to resolve the member's URN. w_member_social is LinkedIn's "Share on LinkedIn"
        # posting permission — requires that product's approval in the LinkedIn Developer
        # Portal, a manual step outside this plugin's code (see README §"Auth setup").
        scopes=("openid", "profile", "w_member_social"),
        pkce="unsupported",  # LinkedIn's OAuth2 implementation does not support PKCE
        # LinkedIn's /oauth/v2/accessToken expects client_id/client_secret as form-encoded
        # POST body params, not an HTTP Basic Authorization header.
        token_endpoint_auth_method="client_secret_post",
    ),
)
