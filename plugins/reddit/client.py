"""Raw Reddit API HTTP client — see plugins/reddit/README.md.

Deliberately NOT PRAW (Reddit's own client library, recommended in this plugin's README
before the generic OAuth2 framework existed — see
docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md). PRAW manages its own OAuth token
lifecycle (initial auth + refresh against Reddit directly), which would duplicate
docs/auth/OAUTH2_ARCHITECTURE.md's platform mechanism instead of using it. This is a thin
httpx wrapper around Reddit's REST API using an already-valid access token the platform hands
this plugin via `ResolvedConnection.credentials` — this plugin never manages a token's
lifecycle itself, only uses one it's given.
"""

from __future__ import annotations

from typing import Any

import httpx

from plugins.reddit.manifest import USER_AGENT

_BASE_URL = "https://oauth.reddit.com"
# Reddit's public, unauthenticated listing/search endpoints — no OAuth token needed, used for
# sitewide lead discovery before a project has ever connected a Reddit account. See
# plugins/reddit/plugin.py's search() and README.md's "Public sitewide search" section.
_PUBLIC_BASE_URL = "https://www.reddit.com"
_HTTP_TIMEOUT_SECONDS = 10.0


class RedditAPIError(Exception):
    """Raised on an HTTP-level failure (unreachable, non-2xx status) or a Reddit
    API-level failure (Reddit's legacy endpoints, e.g. `/api/comment`, return HTTP 200 with
    errors listed inside the JSON body — treated identically here so callers only ever check
    one thing). Caught inside `RedditPlugin.publish()` and converted to a
    `PublishResult(success=False, ...)` — see `plugins/_shared/base.py`'s `Publishable`
    docstring and this plugin's README §"Known constraints". Allowed to propagate from
    `search()` (caught there, see `plugin.py`) and `health_check()` (caught there, converted
    to `False`) — neither has a partial-failure result shape to encode it in otherwise."""


async def _do_request(method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> dict:
    """The actual HTTP round trip + Reddit's own response-shape quirks, shared by every
    authenticated `RedditClient` call and by the module-level `search_public()` below — the
    only difference between the two is which headers/base URL get used, never this logic."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise RedditAPIError(f"Could not reach Reddit: {exc}") from exc

    if response.status_code >= 400:
        raise RedditAPIError(f"Reddit returned {response.status_code}: {response.text[:500]}")

    try:
        body = response.json()
    except ValueError as exc:
        raise RedditAPIError(f"Reddit returned a non-JSON response: {response.text[:500]}") from exc

    # Reddit's legacy "api_type=json" endpoints (e.g. /api/comment) return HTTP 200 even
    # when the operation failed — the actual error lives in body["json"]["errors"].
    if isinstance(body, dict):
        json_field = body.get("json")
        errors = json_field.get("errors") if isinstance(json_field, dict) else None
        if errors:
            raise RedditAPIError(f"Reddit rejected the request: {errors}")

    return body if isinstance(body, dict) else {}


async def search_public(terms: list[str], *, limit: int) -> list[dict]:
    """`GET /search.json` on `www.reddit.com` — sitewide, unauthenticated search across every
    subreddit, no OAuth token or connected account required. This is the discovery mechanism
    for the "no login needed to find leads" product design (see
    plugins/reddit/plugin.py's search() and README.md) — `submit_comment()`/`me()` above still
    always require a real OAuth token; only search works unauthenticated. Each returned post
    already carries its own `"subreddit"` field (Reddit's listing JSON shape is identical
    authenticated or not), so callers don't need to track which subreddit a result came from."""
    params = {"q": " OR ".join(terms), "sort": "new", "limit": str(limit)}
    body = await _do_request(
        "GET",
        f"{_PUBLIC_BASE_URL}/search.json",
        headers={"User-Agent": USER_AGENT},
        params=params,
    )
    children = body.get("data", {}).get("children", [])
    return [child["data"] for child in children if "data" in child]


class RedditClient:
    def __init__(self, *, access_token: str) -> None:
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}", "User-Agent": USER_AGENT}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        return await _do_request(method, f"{_BASE_URL}{path}", headers=self._headers(), **kwargs)

    async def me(self) -> dict:
        """`GET /api/v1/me` — used by `health_check()` to verify the token actually works,
        not just that it hasn't expired locally. Requires the `identity` scope."""
        return await self._request("GET", "/api/v1/me")

    async def search_subreddit(self, subreddit: str, query: str, *, limit: int) -> list[dict]:
        """`GET /r/{subreddit}/search`, restricted to that subreddit, sorted by newest
        first."""
        params = {"q": query, "restrict_sr": "1", "sort": "new", "limit": str(limit)}
        data = await self._request("GET", f"/r/{subreddit}/search", params=params)
        children = data.get("data", {}).get("children", [])
        return [child["data"] for child in children if "data" in child]

    async def submit_comment(self, *, thing_id: str, text: str) -> dict:
        """`POST /api/comment` — replies to `thing_id` (a Reddit "fullname", e.g. `t3_abc123`
        for a submission or `t1_xyz789` for a comment)."""
        data = {"thing_id": thing_id, "text": text, "api_type": "json"}
        return await self._request("POST", "/api/comment", data=data)


__all__ = ["RedditAPIError", "RedditClient", "search_public"]
