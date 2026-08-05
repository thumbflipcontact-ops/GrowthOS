"""Raw LinkedIn API HTTP client — see plugins/linkedin/README.md.

A thin httpx wrapper around LinkedIn's OpenID Connect userinfo endpoint and its Posts API,
using an already-valid access token the platform hands this plugin via
`ResolvedConnection.credentials` — this plugin never manages a token's lifecycle itself, only
uses one it's given (same division of responsibility as plugins/reddit/client.py and
plugins/twitter/client.py).
"""

from __future__ import annotations

from typing import Any

import httpx

_BASE_URL = "https://api.linkedin.com"
_HTTP_TIMEOUT_SECONDS = 10.0

# LinkedIn's Posts API requires a version pin on every call, in YYYYMM format, valid for a
# rolling window before LinkedIn deprecates it — see
# https://learn.microsoft.com/en-us/linkedin/marketing/versioning. This needs periodic
# operator upkeep (bump the string, redeploy), the same kind of maintenance burden as
# Reddit's User-Agent string but on LinkedIn's clock, not this plugin's — see README
# §"Known constraints".
_LINKEDIN_API_VERSION = "202401"


class LinkedInAPIError(Exception):
    """Raised on an HTTP-level failure (unreachable, non-2xx status) or a malformed
    response. Caught inside `LinkedInPlugin.publish()`/`health_check()`, mirroring
    plugins/reddit/client.py's RedditAPIError and plugins/twitter/client.py's
    TwitterAPIError."""


class LinkedInClient:
    def __init__(self, *, access_token: str) -> None:
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    def _posts_headers(self) -> dict[str, str]:
        return {
            **self._headers(),
            "LinkedIn-Version": _LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.request(method, f"{_BASE_URL}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise LinkedInAPIError(f"Could not reach LinkedIn: {exc}") from exc

        if response.status_code >= 400:
            raise LinkedInAPIError(
                f"LinkedIn returned {response.status_code}: {_error_detail(response)}"
            )
        return response

    async def userinfo(self) -> dict:
        """`GET /v2/userinfo` — the OpenID Connect standard claims endpoint. Used by
        `health_check()` to verify the token actually works, and by `publish()` to resolve
        the member's numeric id (`sub`) into the URN LinkedIn's Posts API requires as
        `author`. Requires the `openid`/`profile` scopes."""
        response = await self._send("GET", "/v2/userinfo", headers=self._headers())
        return _parse_body(response)

    async def create_post(self, *, person_id: str, text: str, visibility: str) -> dict:
        """`POST /rest/posts` — LinkedIn's current Posts API (superseding the older
        `/v2/ugcPosts`). Requires the `w_member_social` scope and that app's "Share on
        LinkedIn" product access to be approved in the LinkedIn Developer Portal.

        Returns `{"id": <post URN or None>}`. LinkedIn's Restli-style create endpoints
        commonly return `201 Created` with an **empty body**, the new entity's id in an
        `x-restli-id` (or `x-linkedin-id`) response header instead — `_extract_post_id`
        checks both the body and the header so callers only ever look at one field. This
        client has been built against LinkedIn's published API docs but not yet exercised
        against a real account/app — see README §"Known constraints".
        """
        payload = {
            "author": f"urn:li:person:{person_id}",
            "commentary": text,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        response = await self._send(
            "POST", "/rest/posts", headers=self._posts_headers(), json=payload
        )
        return {"id": _extract_post_id(response)}


def _parse_body(response: httpx.Response) -> dict:
    if not response.text:
        return {}
    try:
        body = response.json()
    except ValueError as exc:
        raise LinkedInAPIError(
            f"LinkedIn returned a non-JSON response: {response.text[:500]}"
        ) from exc
    return body if isinstance(body, dict) else {}


def _extract_post_id(response: httpx.Response) -> str | None:
    body = _parse_body(response)
    if body.get("id"):
        return str(body["id"])
    return response.headers.get("x-restli-id") or response.headers.get("x-linkedin-id")


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        detail = body.get("message") or body.get("error_description") or body.get("error")
        if detail:
            return str(detail)
    return response.text[:500]


__all__ = ["LinkedInAPIError", "LinkedInClient"]
