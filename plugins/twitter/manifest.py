"""Twitter/X — searchable + publishable via X API v2's OAuth2 flow. See
docs/plugins/PLUGIN_ARCHITECTURE.md, docs/auth/OAUTH2_ARCHITECTURE.md, and
plugins/twitter/README.md.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins._shared.manifest import ContentTypeSpec, PluginManifest
from plugins._shared.oauth import OAuthProviderSpec


class TwitterConnectionConfig(BaseModel):
    """X's recent-search endpoint has no per-connection "which subreddit" equivalent — it
    searches all public posts by default, scoped only by `PluginQuery.terms` at call time.
    What *is* connection-level is how noisy that search is allowed to be, hence these
    filters rather than a Reddit-style allowlist."""

    exclude_retweets: bool = True
    exclude_replies: bool = False
    lang: str | None = Field(default=None, description="ISO 639-1 code, e.g. 'en'.")


MANIFEST = PluginManifest(
    key="twitter",
    interface_version="1.0",
    capabilities=("searchable", "publishable"),
    content_types=(
        # 280 is the standard (non-Premium) per-tweet limit. GrowthOS does not assume a
        # Premium/X Blue account with the higher 25,000-character limit — see README
        # §"Known constraints".
        ContentTypeSpec(key="tweet", max_length=280, publish_target="tweet"),
    ),
    config_schema=TwitterConnectionConfig,
    auth_type="oauth2",
    oauth=OAuthProviderSpec(
        authorize_url="https://twitter.com/i/oauth2/authorize",
        token_url="https://api.twitter.com/2/oauth2/token",
        revoke_url="https://api.twitter.com/2/oauth2/revoke",
        # offline.access is required to receive a refresh_token at all — without it X issues
        # a 2-hour access token with no way to refresh it, silently breaking the platform's
        # background refresh job, the same failure mode documented for Reddit's
        # duration=permanent. users.read backs health_check()'s GET /2/users/me call.
        scopes=("tweet.read", "tweet.write", "users.read", "offline.access"),
        # X API v2's OAuth 2.0 Authorization Code flow requires PKCE unconditionally, for
        # both confidential and public clients — the reason this platform's OAuth2 framework
        # supported PKCE from the start (see docs/auth/OAUTH2_ARCHITECTURE.md's original
        # design rationale).
        pkce="required",
        # GrowthOS registers as a confidential client (it holds a client_secret) — X's docs
        # specify HTTP Basic auth (client_id:client_secret) for confidential clients at the
        # token endpoint.
        token_endpoint_auth_method="client_secret_basic",
    ),
)
