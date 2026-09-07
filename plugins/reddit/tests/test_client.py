"""Unit tests for RedditClient — see plugins/reddit/client.py. Uses httpx.MockTransport
(same technique as backend/tests/unit/test_oauth_client.py) so every test exercises a real
HTTP request/response round trip without ever reaching the network.
"""

from __future__ import annotations

import httpx
import pytest

from plugins.reddit.client import RedditAPIError, RedditClient, search_public

# A real response captured from GET https://www.reddit.com/search.rss?q=startup&sort=new —
# see plugins/reddit/README.md's "Public sitewide search" section for why RSS, not JSON
# (GET /search.json returns HTTP 403 with a bot-detection page from a datacenter IP; RSS
# doesn't). First entry is a subreddit-description entry (t5_...) Reddit mixes into search
# results, not an actual post — real search responses always include this, so a correct
# parser must skip it via the t3_ prefix check, not just happen to work on trimmed fixtures.
_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<content type="html">&lt;div&gt; A subreddit about startups. &lt;/div&gt;</content>
<id>t5_2qhyd</id>
<link href="https://www.reddit.com/r/startup/" />
<updated>2008-05-09T02:35:47+00:00</updated>
<title>Reddit's Startup Community</title>
</entry>
<entry>
<author><name>/u/Sensitive_Hawk425</name><uri>https://www.reddit.com/user/Sensitive_Hawk425</uri></author>
<category term="careerquestions" label="r/careerquestions"/>
<content type="html">&lt;!-- SC_OFF --&gt;&lt;div class=&quot;md&quot;&gt;&lt;p&gt;Assume you are doing B.Tech.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; &amp;#32; submitted by &amp;#32; &lt;a href=&quot;https://www.reddit.com/user/Sensitive_Hawk425&quot;&gt; /u/Sensitive_Hawk425 &lt;/a&gt; &amp;#32; to &amp;#32; &lt;a href=&quot;https://www.reddit.com/r/careerquestions/&quot;&gt; r/careerquestions &lt;/a&gt; &lt;br/&gt; &lt;span&gt;&lt;a href=&quot;https://www.reddit.com/r/careerquestions/comments/1w9n1e9/what/&quot;&gt;[link]&lt;/a&gt;&lt;/span&gt;</content>
<id>t3_1w9n1e9</id>
<link href="https://www.reddit.com/r/careerquestions/comments/1w9n1e9/what_would_you_do/" />
<updated>2026-09-07T09:07:56+00:00</updated>
<published>2026-09-07T09:07:56+00:00</published>
<title>What would you do and why? IT? Government Exam? Business?</title>
</entry>
</feed>"""


def _patch_async_client(monkeypatch, handler) -> None:
    import plugins.reddit.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_requests_include_bearer_token_and_user_agent(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"name": "growthos-bot"})

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at-123")
    await client.me()

    assert captured["authorization"] == "Bearer at-123"
    assert captured["user_agent"] == "growthos:platform:v1.0 (by /u/growthos-app)"


@pytest.mark.asyncio
async def test_me_returns_parsed_json(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "growthos-bot", "id": "abc123"})

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    result = await client.me()

    assert result == {"name": "growthos-bot", "id": "abc123"}


@pytest.mark.asyncio
async def test_me_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid_token")

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="expired")
    with pytest.raises(RedditAPIError):
        await client.me()


@pytest.mark.asyncio
async def test_raises_on_network_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    with pytest.raises(RedditAPIError):
        await client.me()


@pytest.mark.asyncio
async def test_raises_on_non_json_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    with pytest.raises(RedditAPIError):
        await client.me()


@pytest.mark.asyncio
async def test_search_subreddit_extracts_post_data(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/r/SEO/search"
        assert request.url.params["q"] == "indexing"
        assert request.url.params["restrict_sr"] == "1"
        return httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {"kind": "t3", "data": {"title": "Post 1", "name": "t3_a"}},
                        {"kind": "t3", "data": {"title": "Post 2", "name": "t3_b"}},
                    ]
                }
            },
        )

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    posts = await client.search_subreddit("SEO", "indexing", limit=25)

    assert [p["title"] for p in posts] == ["Post 1", "Post 2"]


@pytest.mark.asyncio
async def test_search_subreddit_handles_empty_results(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"children": []}})

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    posts = await client.search_subreddit("SEO", "nonsense-query-xyz", limit=25)

    assert posts == []


@pytest.mark.asyncio
async def test_submit_comment_success(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "json": {
                    "errors": [],
                    "data": {
                        "things": [{"kind": "t1", "data": {"permalink": "/r/SEO/comments/x/y/"}}]
                    },
                }
            },
        )

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    result = await client.submit_comment(thing_id="t3_abc123", text="Great point!")

    assert captured["body"]["thing_id"] == ["t3_abc123"]
    assert captured["body"]["text"] == ["Great point!"]
    assert result["json"]["data"]["things"][0]["data"]["permalink"] == "/r/SEO/comments/x/y/"


@pytest.mark.asyncio
async def test_submit_comment_raises_on_reddit_level_error_despite_200(monkeypatch) -> None:
    # Reddit's legacy api_type=json endpoints return HTTP 200 even when the operation
    # logically failed — the client must still surface this as a failure.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"json": {"errors": [["RATELIMIT", "you are doing that too much", "ratelimit"]]}},
        )

    _patch_async_client(monkeypatch, handler)
    client = RedditClient(access_token="at")
    with pytest.raises(RedditAPIError):
        await client.submit_comment(thing_id="t3_abc123", text="hello")


@pytest.mark.asyncio
async def test_search_public_hits_search_rss_not_search_json(monkeypatch) -> None:
    # Regression test for the actual production bug: GET /search.json returns HTTP 403 (a
    # bot-detection page) from a datacenter IP, silently swallowed by RedditPlugin.search()
    # into "0 raw results" with no visible error. RSS is confirmed to work — see README.md.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search.rss"
        assert request.url.params["q"] == "startup"
        return httpx.Response(200, text=_SAMPLE_RSS)

    _patch_async_client(monkeypatch, handler)
    await search_public(["startup"], limit=25)


@pytest.mark.asyncio
async def test_search_public_skips_the_subreddit_metadata_entry(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_SAMPLE_RSS)

    _patch_async_client(monkeypatch, handler)
    posts = await search_public(["startup"], limit=25)

    # Only the real t3_ post, not the t5_ subreddit-description entry mixed into the feed.
    assert len(posts) == 1
    assert posts[0]["name"] == "t3_1w9n1e9"


@pytest.mark.asyncio
async def test_search_public_maps_fields_to_the_json_api_shape(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_SAMPLE_RSS)

    _patch_async_client(monkeypatch, handler)
    [post] = await search_public(["startup"], limit=25)

    assert post["title"] == "What would you do and why? IT? Government Exam? Business?"
    # Relative path, matching the JSON API's own convention — not RSS's full URL.
    assert post["permalink"] == "/r/careerquestions/comments/1w9n1e9/what_would_you_do/"
    assert post["author"] == "Sensitive_Hawk425"
    assert post["subreddit"] == "careerquestions"
    assert "Assume you are doing B.Tech." in post["selftext"]
    # The "submitted by ... [link]" boilerplate Reddit appends must not leak into the body.
    assert "submitted by" not in post["selftext"]
    assert post["created_utc"] > 0


@pytest.mark.asyncio
async def test_search_public_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>bot check</html>")

    _patch_async_client(monkeypatch, handler)
    with pytest.raises(RedditAPIError):
        await search_public(["startup"], limit=25)


@pytest.mark.asyncio
async def test_search_public_raises_on_unparseable_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not xml at all")

    _patch_async_client(monkeypatch, handler)
    with pytest.raises(RedditAPIError):
        await search_public(["startup"], limit=25)


@pytest.mark.asyncio
async def test_search_public_handles_no_results(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
        )

    _patch_async_client(monkeypatch, handler)
    posts = await search_public(["startup"], limit=25)

    assert posts == []
