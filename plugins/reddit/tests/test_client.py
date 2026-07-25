"""Unit tests for RedditClient — see plugins/reddit/client.py. Uses httpx.MockTransport
(same technique as backend/tests/unit/test_oauth_client.py) so every test exercises a real
HTTP request/response round trip without ever reaching the network.
"""

from __future__ import annotations

import httpx
import pytest

from plugins.reddit.client import RedditAPIError, RedditClient


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
