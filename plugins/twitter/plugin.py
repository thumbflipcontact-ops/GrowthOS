"""Twitter/X plugin — Searchable + Publishable. See plugins/twitter/README.md,
docs/plugins/PLUGIN_ARCHITECTURE.md, and docs/auth/OAUTH2_ARCHITECTURE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from plugins._shared.base import PluginQuery, PluginResult, PublishResult, ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.twitter.client import TwitterAPIError, TwitterClient
from plugins.twitter.manifest import MANIFEST, TwitterConnectionConfig

# One shared limiter across every TwitterPlugin instance in this process — a fresh instance
# is constructed on every registry lookup (app/core/plugin_registry.py), so per-instance
# state would reset each call and never actually limit anything. Matches X API v2's Basic
# tier recent-search limit of 60 requests/15 minutes per app (README §"Rate limits") — the
# tightest of the endpoints this plugin calls, so it's used as the shared budget.
_RATE_LIMITER = RateLimiter(capacity=60, refill_rate=60 / 900)


class TwitterPlugin:
    manifest = MANIFEST

    def __init__(self, connection: ResolvedConnection) -> None:
        self._connection = connection
        self._config = TwitterConnectionConfig.model_validate(connection.config)
        self._client = _build_client(connection)

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        if self._client is None or not query.terms:
            return []
        if not self._try_acquire():
            return []  # throttled — never raise, see RateLimiter's documented contract

        search_query = _build_search_query(query.terms, self._config)
        try:
            body = await self._client.search_recent(search_query, max_results=query.limit)
        except TwitterAPIError:
            return []

        users_by_id = {u["id"]: u for u in body.get("includes", {}).get("users", [])}
        results: list[PluginResult] = []
        for tweet in body.get("data", []):
            if query.since is not None and _created_at(tweet) < query.since:
                continue
            results.append(_to_plugin_result(tweet, users_by_id))
            if len(results) >= query.limit:
                break
        return results

    async def publish(self, item: object) -> PublishResult:
        if self._client is None:
            return PublishResult(
                success=False,
                published_url=None,
                error="This X connection has no valid credentials yet — connect or "
                "reconnect it.",
            )

        body = getattr(item, "body", None)
        if not body:
            return PublishResult(success=False, published_url=None, error="item is missing body.")
        reply_to = getattr(item, "target_ref", None) or None

        if not self._try_acquire():
            return PublishResult(
                success=False, published_url=None, error="Rate limited — try again shortly."
            )

        try:
            response = await self._client.create_tweet(text=body, reply_to_tweet_id=reply_to)
        except TwitterAPIError as exc:
            return PublishResult(success=False, published_url=None, error=str(exc))

        return PublishResult(success=True, published_url=_published_url(response), error=None)

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.me()
        except TwitterAPIError:
            return False
        return True

    def _try_acquire(self) -> bool:
        return _RATE_LIMITER.try_acquire(
            plugin_key=self._connection.plugin_key, project_id=str(self._connection.project_id)
        )


def _build_client(connection: ResolvedConnection) -> TwitterClient | None:
    if not isinstance(connection.credentials, OAuth2Credentials):
        return None
    return TwitterClient(access_token=connection.credentials.access_token)


def _build_search_query(terms: list[str], config: TwitterConnectionConfig) -> str:
    joined = " OR ".join(terms)
    query = f"({joined})" if len(terms) > 1 else joined
    if config.exclude_retweets:
        query += " -is:retweet"
    if config.exclude_replies:
        query += " -is:reply"
    if config.lang:
        query += f" lang:{config.lang}"
    return query


def _created_at(tweet: dict) -> datetime:
    raw = tweet.get("created_at")
    if not raw:
        return datetime.fromtimestamp(0, tz=UTC)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _to_plugin_result(tweet: dict, users_by_id: dict) -> PluginResult:
    author = users_by_id.get(tweet.get("author_id"))
    username = author.get("username") if author else None
    tweet_id = tweet.get("id", "")
    return PluginResult(
        url=f"https://twitter.com/i/web/status/{tweet_id}",
        title=None,
        body=tweet.get("text") or "",
        author=username,
        platform_metadata={"tweet_id": tweet_id, "author_id": tweet.get("author_id")},
    )


def _published_url(response: dict) -> str | None:
    tweet_id = response.get("data", {}).get("id")
    return f"https://twitter.com/i/web/status/{tweet_id}" if tweet_id else None


def create_plugin(connection: ResolvedConnection) -> TwitterPlugin:
    return TwitterPlugin(connection)
