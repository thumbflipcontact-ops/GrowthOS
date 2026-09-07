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

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

from plugins.reddit.manifest import USER_AGENT

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_SC_BOUNDARY_RE = re.compile(r"<!--\s*SC_OFF\s*-->(.*?)<!--\s*SC_ON\s*-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

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


def _clean_rss_body(content_html: str) -> str:
    """RSS wraps a self-post's actual text between SC_OFF/SC_ON HTML comments, followed by
    Reddit's own "submitted by ... to r/... [link] [comments]" boilerplate — this strips both
    the boilerplate and the remaining HTML tags/entities down to plain text."""
    match = _SC_BOUNDARY_RE.search(content_html)
    text = match.group(1) if match else content_html
    return _WHITESPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", text))).strip()


def _parse_search_rss(xml_text: str) -> list[dict]:
    """Maps Atom `<entry>` elements to the same dict shape the (now-blocked, see below)
    JSON search endpoint produced, so plugin.py's `_to_plugin_result`/`_created_at` need no
    changes at all: `name` (Reddit fullname/thing_id — RSS's `<id>` *is* this, no lookup
    needed), `title`, `permalink` (relative path, matching the JSON API's own convention —
    RSS gives a full URL, stripped here), `selftext`, `author`, `subreddit`, `created_utc`
    (RSS gives ISO 8601, converted to the epoch float the JSON shape always used). `score`/
    `num_comments` don't exist in RSS at all — omitted; nothing downstream reads them."""
    root = ET.fromstring(xml_text)
    posts: list[dict] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        thing_id = entry.findtext("atom:id", default="", namespaces=_ATOM_NS)
        if not thing_id.startswith("t3_"):
            continue  # e.g. a subreddit-description entry (t5_...) mixed into search results

        link_el = entry.find("atom:link", _ATOM_NS)
        permalink = urlparse(link_el.get("href", "")).path if link_el is not None else ""
        author_name = entry.findtext("atom:author/atom:name", default="", namespaces=_ATOM_NS)
        category_el = entry.find("atom:category", _ATOM_NS)
        published = entry.findtext("atom:published", namespaces=_ATOM_NS) or entry.findtext(
            "atom:updated", namespaces=_ATOM_NS
        )
        created_utc = datetime.fromisoformat(published).timestamp() if published else 0

        posts.append(
            {
                "name": thing_id,
                "title": entry.findtext("atom:title", default="", namespaces=_ATOM_NS),
                "permalink": permalink,
                "selftext": _clean_rss_body(
                    entry.findtext("atom:content", default="", namespaces=_ATOM_NS)
                ),
                "author": author_name.removeprefix("/u/") if author_name else None,
                "subreddit": category_el.get("term") if category_el is not None else None,
                "created_utc": created_utc,
            }
        )
    return posts


async def search_public(terms: list[str], *, limit: int) -> list[dict]:
    """`GET /search.rss` on `www.reddit.com` — sitewide, unauthenticated search across every
    subreddit, no OAuth token or connected account required. This is the discovery mechanism
    for the "no login needed to find leads" product design (see plugins/reddit/plugin.py's
    search() and README.md) — `submit_comment()`/`me()` above still always require a real
    OAuth token; only search works unauthenticated.

    RSS, not the JSON search endpoint: confirmed by direct production testing that
    `GET /search.json` returns HTTP 403 with a bot-detection HTML challenge page from
    Railway's IP range, while `GET /search.rss` returns a normal 200 with real Atom XML —
    matching MentionCatch's own stated architecture ("reads Reddit's public RSS feeds and
    search results"). `RedditPlugin.search()` swallows a `RedditAPIError` into `[]` rather
    than surfacing it, which is exactly what silently masked the JSON endpoint's 403s as
    "0 raw results" instead of a visible error — see plugin.py's search()."""
    params = {"q": " OR ".join(terms), "sort": "new", "limit": str(limit)}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{_PUBLIC_BASE_URL}/search.rss",
                headers={"User-Agent": USER_AGENT},
                params=params,
            )
    except httpx.HTTPError as exc:
        raise RedditAPIError(f"Could not reach Reddit: {exc}") from exc

    if response.status_code >= 400:
        raise RedditAPIError(f"Reddit returned {response.status_code}: {response.text[:500]}")

    try:
        return _parse_search_rss(response.text)
    except ET.ParseError as exc:
        raise RedditAPIError(f"Reddit returned an unparseable RSS response: {exc}") from exc


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
