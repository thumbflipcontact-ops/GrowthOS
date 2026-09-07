"""Reddit plugin — Searchable + Publishable. See plugins/reddit/README.md,
docs/plugins/PLUGIN_ARCHITECTURE.md, and docs/auth/OAUTH2_ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from plugins._shared.base import PluginQuery, PluginResult, PublishResult, ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.reddit.client import RedditAPIError, RedditClient, search_public
from plugins.reddit.manifest import MANIFEST, RedditConnectionConfig

# One shared limiter across every RedditPlugin instance in this process for OAuth-authenticated
# calls (publish, health_check) — a fresh instance is constructed on every registry lookup
# (app/core/plugin_registry.py), so per-instance state would reset each call and never actually
# limit anything. Matches Reddit's documented ~60 requests/minute per OAuth client (README
# §"Rate limits").
_RATE_LIMITER = RateLimiter(capacity=60, refill_rate=1.0)

# Reddit's public, unauthenticated search endpoint is far more easily rate-limited/blocked than
# the OAuth API, and — unlike _RATE_LIMITER above — it's hit from one shared outbound IP across
# every Threadly project, not a per-user OAuth client. Deliberately conservative (10/min) and a
# single shared bucket (_PUBLIC_BUCKET_KEY, not a real project_id) rather than one budget per
# project. See README.md's "Public sitewide search" section.
_PUBLIC_RATE_LIMITER = RateLimiter(capacity=10, refill_rate=10 / 60)
_PUBLIC_BUCKET_KEY = "shared"


class RedditPlugin:
    manifest = MANIFEST

    def __init__(self, connection: ResolvedConnection) -> None:
        self._connection = connection
        # Not read by search() below (public search is sitewide, not subreddit-scoped) — kept
        # for config-shape validation and for search_subreddit()'s dormant, not-yet-wired-in
        # per-subreddit mode (client.py), which a future power-user feature could reuse.
        self._config = RedditConnectionConfig.model_validate(connection.config)
        self._client = _build_client(connection)

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        """Sitewide, unauthenticated search — works whether or not this project has ever
        connected a Reddit account, matching the product's "no login needed to find leads"
        design (see README.md). Connecting an account (OAuth) is only ever required for
        publish(), never for search()."""
        if not query.terms:
            return []
        if not _PUBLIC_RATE_LIMITER.try_acquire(plugin_key="reddit", project_id=_PUBLIC_BUCKET_KEY):
            return []  # throttled — never raise, matches every other plugin's rate-limit contract

        try:
            posts = await search_public(query.terms, limit=query.limit)
        except RedditAPIError:
            return []

        results: list[PluginResult] = []
        for post in posts:
            if query.since is not None and _created_at(post) < query.since:
                continue
            results.append(_to_plugin_result(post))
            if len(results) >= query.limit:
                break

        return results

    async def publish(self, item: object) -> PublishResult:
        if self._client is None:
            return PublishResult(
                success=False,
                published_url=None,
                error="This Reddit connection has no valid credentials yet — connect or "
                "reconnect it.",
            )

        target_ref = getattr(item, "target_ref", None)
        body = getattr(item, "body", None)
        if not target_ref or not body:
            return PublishResult(
                success=False, published_url=None, error="item is missing target_ref or body."
            )

        if not self._try_acquire():
            return PublishResult(
                success=False, published_url=None, error="Rate limited — try again shortly."
            )

        try:
            response = await self._client.submit_comment(thing_id=target_ref, text=body)
        except RedditAPIError as exc:
            # Surfaced verbatim, not swallowed — see README §"Known constraints" (Reddit's
            # spam filters can shadow-affect new/low-karma accounts; a failed post must be
            # visible, not silently retried into invisibility).
            return PublishResult(success=False, published_url=None, error=str(exc))

        return PublishResult(success=True, published_url=_published_url(response), error=None)

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.me()
        except RedditAPIError:
            return False
        return True

    def _try_acquire(self) -> bool:
        return _RATE_LIMITER.try_acquire(
            plugin_key=self._connection.plugin_key, project_id=str(self._connection.project_id)
        )


def _build_client(connection: ResolvedConnection) -> RedditClient | None:
    if not isinstance(connection.credentials, OAuth2Credentials):
        return None
    return RedditClient(access_token=connection.credentials.access_token)


def _created_at(post: dict) -> datetime:
    return datetime.fromtimestamp(post.get("created_utc", 0), tz=UTC)


def _to_plugin_result(post: dict) -> PluginResult:
    return PluginResult(
        url=f"https://reddit.com{post.get('permalink', '')}",
        title=post.get("title"),
        body=post.get("selftext") or "",
        author=post.get("author"),
        platform_metadata={
            "subreddit": post.get("subreddit"),
            "thing_id": post.get("name"),
            "score": post.get("score"),
            "num_comments": post.get("num_comments"),
        },
    )


def _published_url(response: dict) -> str | None:
    try:
        things = response["json"]["data"]["things"]
        permalink = things[0]["data"].get("permalink")
    except (KeyError, IndexError, TypeError):
        return None
    return f"https://reddit.com{permalink}" if permalink else None


def create_plugin(connection: ResolvedConnection) -> RedditPlugin:
    return RedditPlugin(connection)
