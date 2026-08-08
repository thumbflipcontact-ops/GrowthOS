"""Raw X (Twitter) API v2 HTTP client — see plugins/twitter/README.md.

A thin httpx wrapper around X API v2 using an already-valid access token the platform hands
this plugin via `ResolvedConnection.credentials` — this plugin never manages a token's
lifecycle itself, only uses one it's given (same division of responsibility as
plugins/reddit/client.py).
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE_URL = "https://api.twitter.com/2"
_HTTP_TIMEOUT_SECONDS = 10.0

# X API v2's recent-search endpoint rejects max_results outside this range.
_SEARCH_MIN_RESULTS = 10
_SEARCH_MAX_RESULTS = 100


class TwitterAPIError(Exception):
    """Raised on an HTTP-level failure (unreachable, non-2xx status) or a malformed
    response. X API v2 error bodies are RFC 7807 problem+json (`title`/`detail`/`type`) on
    hard failures, or a top-level `errors` array alongside partial `data` on soft ones —
    `_request()` surfaces whichever is present so callers only ever check one thing. Caught
    inside `TwitterPlugin.publish()`/`search()`/`health_check()`, mirroring
    plugins/reddit/client.py's RedditAPIError.

    `status_code` is `None` for a connectivity failure (never reached X at all) and set to
    the actual HTTP status for anything X responded with — callers that need to tell "the
    platform's own X app is out of pay-per-use credits" (402) apart from an ordinary failure
    do so by checking this rather than parsing the message string."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TwitterClient:
    def __init__(self, *, access_token: str) -> None:
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method, f"{_BASE_URL}{path}", headers=self._headers(), **kwargs
                )
        except httpx.HTTPError as exc:
            raise TwitterAPIError(f"Could not reach X: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                raise TwitterAPIError(
                    f"X returned {response.status_code}: {response.text[:500]}",
                    status_code=response.status_code,
                ) from exc
            raise TwitterAPIError(f"X returned a non-JSON response: {response.text[:500]}") from exc

        if response.status_code >= 400:
            detail = _error_detail(body) if isinstance(body, dict) else None
            raise TwitterAPIError(
                f"X returned {response.status_code}: {detail or response.text[:500]}",
                status_code=response.status_code,
            )

        return body if isinstance(body, dict) else {}

    async def me(self) -> dict:
        """`GET /2/users/me` — used by `health_check()` to verify the token actually works,
        not just that it hasn't expired locally. Requires the `users.read` scope."""
        return await self._request("GET", "/users/me")

    async def search_recent(self, query: str, *, max_results: int) -> dict:
        """`GET /2/tweets/search/recent`. Returns the raw response body (`data` +
        `includes.users`) rather than a flattened list — the plugin needs both to build a
        `PluginResult` with an author's username, not just their opaque numeric id."""
        clamped = max(_SEARCH_MIN_RESULTS, min(_SEARCH_MAX_RESULTS, max_results))
        params = {
            "query": query,
            "max_results": str(clamped),
            "tweet.fields": "created_at,author_id",
            "expansions": "author_id",
            "user.fields": "username",
        }
        return await self._request("GET", "/tweets/search/recent", params=params)

    async def create_tweet(self, *, text: str, reply_to_tweet_id: str | None = None) -> dict:
        """`POST /2/tweets` — a new tweet, or a reply if `reply_to_tweet_id` is given."""
        payload: dict[str, Any] = {"text": text}
        if reply_to_tweet_id is not None:
            payload["reply"] = {"in_reply_to_tweet_id": reply_to_tweet_id}
        return await self._request("POST", "/tweets", json=payload)


def _error_detail(body: dict) -> str | None:
    # Hard failures: RFC 7807 problem+json (`detail`/`title`).
    detail = body.get("detail") or body.get("title")
    if detail:
        return str(detail)
    # Soft failures alongside partial data: a top-level `errors` array.
    errors = body.get("errors")
    if errors:
        return str(errors)
    return None


__all__ = ["TwitterAPIError", "TwitterClient"]
