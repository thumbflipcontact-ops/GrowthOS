"""Unit tests for TwitterClient — see plugins/twitter/client.py. Uses httpx.MockTransport
(same technique as plugins/reddit/tests/test_client.py) so every test exercises a real
HTTP request/response round trip without ever reaching the network.
"""

from __future__ import annotations

import httpx
import pytest

from plugins.twitter.client import TwitterAPIError, TwitterClient


def _patch_async_client(monkeypatch, handler) -> None:
    import plugins.twitter.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_requests_include_bearer_token(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"id": "1", "username": "growthos_bot"}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at-123")
    await client.me()

    assert captured["authorization"] == "Bearer at-123"


@pytest.mark.asyncio
async def test_me_returns_parsed_json(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"id": "1", "username": "growthos_bot"}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    result = await client.me()

    assert result == {"data": {"id": "1", "username": "growthos_bot"}}


@pytest.mark.asyncio
async def test_me_raises_on_error_status_with_problem_json(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"title": "Unauthorized", "type": "about:blank", "status": 401}
        )

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="expired")
    with pytest.raises(TwitterAPIError, match="Unauthorized") as excinfo:
        await client.me()
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_raises_with_status_code_on_credits_depleted(monkeypatch) -> None:
    """X's pay-per-use billing returns 402 when the app's prepaid credits run out — this is
    the exact failure mode TwitterPlugin.search() needs to tell apart from an ordinary
    failure (see plugins/twitter/plugin.py and agents/conversation_finder/agent.py)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"title": "credits depleted"})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    with pytest.raises(TwitterAPIError) as excinfo:
        await client.me()
    assert excinfo.value.status_code == 402


@pytest.mark.asyncio
async def test_raises_on_network_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    with pytest.raises(TwitterAPIError):
        await client.me()


@pytest.mark.asyncio
async def test_raises_on_non_json_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    with pytest.raises(TwitterAPIError):
        await client.me()


@pytest.mark.asyncio
async def test_search_recent_sends_expected_params_and_clamps_max_results(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/tweets/search/recent"
        assert request.url.params["query"] == "indexing OR crawl budget"
        assert request.url.params["max_results"] == "10"  # clamped up from 3
        assert request.url.params["expansions"] == "author_id"
        return httpx.Response(200, json={"data": [], "includes": {"users": []}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    await client.search_recent("indexing OR crawl budget", max_results=3)


@pytest.mark.asyncio
async def test_search_recent_returns_data_and_includes(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"id": "1", "text": "hello", "author_id": "u1"}],
                "includes": {"users": [{"id": "u1", "username": "founder"}]},
            },
        )

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    result = await client.search_recent("hello", max_results=10)

    assert result["data"][0]["text"] == "hello"
    assert result["includes"]["users"][0]["username"] == "founder"


@pytest.mark.asyncio
async def test_search_recent_handles_empty_results(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "meta": {"result_count": 0}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    result = await client.search_recent("nonsense-query-xyz", max_results=10)

    assert result["data"] == []


@pytest.mark.asyncio
async def test_create_tweet_sends_expected_body(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "999", "text": "Great point!"}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    result = await client.create_tweet(text="Great point!")

    assert captured["body"] == {"text": "Great point!"}
    assert result["data"]["id"] == "999"


@pytest.mark.asyncio
async def test_create_tweet_reply_includes_in_reply_to(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"data": {"id": "1000", "text": "reply"}})

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    await client.create_tweet(text="reply", reply_to_tweet_id="123")

    assert captured["body"]["reply"] == {"in_reply_to_tweet_id": "123"}


@pytest.mark.asyncio
async def test_create_tweet_raises_on_soft_error_alongside_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "errors": [{"message": "You are not permitted to perform this action."}],
                "title": "Forbidden",
            },
        )

    _patch_async_client(monkeypatch, handler)
    client = TwitterClient(access_token="at")
    with pytest.raises(TwitterAPIError, match="Forbidden"):
        await client.create_tweet(text="hello")
