"""Reddit plugin — Searchable + Publishable. See plugins/reddit/README.md,
docs/plugins/PLUGIN_ARCHITECTURE.md, and docs/auth/OAUTH2_ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from plugins._shared.base import PluginQuery, PluginResult, PublishResult, ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.reddit.client import RedditAPIError, RedditClient
from plugins.reddit.manifest import MANIFEST, RedditConnectionConfig

# One shared limiter across every RedditPlugin instance in this process — a fresh instance is
# constructed on every registry lookup (app/core/plugin_registry.py), so per-instance state
# would reset each call and never actually limit anything. Matches Reddit's documented ~60
# requests/minute per OAuth client (README §"Rate limits").
_RATE_LIMITER = RateLimiter(capacity=60, refill_rate=1.0)


class RedditPlugin:
    manifest = MANIFEST

    def __init__(self, connection: ResolvedConnection) -> None:
        self._connection = connection
        self._config = RedditConnectionConfig.model_validate(connection.config)
        self._client = _build_client(connection)

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        if self._client is None or not self._config.subreddits:
            return []

        search_terms = " OR ".join(query.terms)
        results: list[PluginResult] = []
        for subreddit in self._config.subreddits:
            if len(results) >= query.limit:
                break
            if not self._try_acquire():
                break  # throttled — return what we have so far, never raise

            try:
                posts = await self._client.search_subreddit(
                    subreddit, search_terms, limit=query.limit - len(results)
                )
            except RedditAPIError:
                continue  # one subreddit failing must not fail the whole search

            for post in posts:
                if query.since is not None and _created_at(post) < query.since:
                    continue
                results.append(_to_plugin_result(subreddit, post))
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


def _to_plugin_result(subreddit: str, post: dict) -> PluginResult:
    return PluginResult(
        url=f"https://reddit.com{post.get('permalink', '')}",
        title=post.get("title"),
        body=post.get("selftext") or "",
        author=post.get("author"),
        platform_metadata={
            "subreddit": subreddit,
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
