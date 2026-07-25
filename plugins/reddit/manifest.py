"""Reddit — searchable + publishable via Reddit's OAuth2 API. See
docs/plugins/PLUGIN_ARCHITECTURE.md, docs/auth/OAUTH2_ARCHITECTURE.md, and
docs/decisions/0005-first-plugin-reddit.md.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plugins._shared.manifest import ContentTypeSpec, PluginManifest
from plugins._shared.oauth import OAuthProviderSpec


class RedditConnectionConfig(BaseModel):
    """Which subreddits this connection searches — e.g. ScoutSEO might watch `r/SEO`,
    `r/juststart`, `r/bigseo`, `r/TechSEO`. An empty list is valid (a connection can exist,
    fully authorized, before anyone has picked subreddits yet); `search()` just returns
    nothing until it's set."""

    subreddits: list[str] = Field(default_factory=list)


# Reddit requires a descriptive User-Agent on every API call, including the OAuth token
# endpoint itself — see https://github.com/reddit-archive/reddit/wiki/API#rules ("Many
# default User-Agents... are drastically limited to encourage unique and descriptive user
# agent strings"). This identifies the GrowthOS application to Reddit, not any individual
# project or connection, so it's a module constant here rather than per-connection config or
# an operator Settings value — see docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md for
# why this was judged simplest rather than inventing new config plumbing for one string.
USER_AGENT = "growthos:platform:v1.0 (by /u/growthos-app)"

MANIFEST = PluginManifest(
    key="reddit",
    interface_version="1.0",
    capabilities=("searchable", "publishable"),
    content_types=(
        ContentTypeSpec(key="reddit_reply", max_length=10_000, publish_target="thread"),
    ),
    config_schema=RedditConnectionConfig,
    auth_type="oauth2",
    oauth=OAuthProviderSpec(
        authorize_url="https://www.reddit.com/api/v1/authorize",
        token_url="https://www.reddit.com/api/v1/access_token",
        revoke_url="https://www.reddit.com/api/v1/revoke_token",
        # "identity" (not just "read"/"submit") is required for health_check()'s
        # GET /api/v1/me call — verifying the token actually works against Reddit, not just
        # that it hasn't expired locally.
        scopes=("read", "submit", "identity"),
        pkce="unsupported",  # Reddit's OAuth2 implementation does not support PKCE
        token_endpoint_auth_method="client_secret_basic",
        # duration=permanent is required to receive a refresh_token at all — without it,
        # Reddit issues a 1-hour access token with no way to refresh it, which would silently
        # break the platform's background refresh job. See
        # https://github.com/reddit-archive/reddit/wiki/OAuth2#authorization
        extra_authorize_params={"duration": "permanent"},
        extra_token_headers={"User-Agent": USER_AGENT},
    ),
)
