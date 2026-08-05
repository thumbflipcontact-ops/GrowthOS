"""Unit tests for LinkedInClient — see plugins/linkedin/client.py. Uses httpx.MockTransport
(same technique as plugins/reddit/tests/test_client.py and
plugins/twitter/tests/test_client.py) so every test exercises a real HTTP request/response
round trip without ever reaching the network.
"""

from __future__ import annotations

import httpx
import pytest

from plugins.linkedin.client import LinkedInAPIError, LinkedInClient


def _patch_async_client(monkeypatch, handler) -> None:
    import plugins.linkedin.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_userinfo_includes_bearer_token(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        assert request.url.path == "/v2/userinfo"
        return httpx.Response(200, json={"sub": "abc123", "name": "Founder"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at-123")
    await client.userinfo()

    assert captured["authorization"] == "Bearer at-123"


@pytest.mark.asyncio
async def test_userinfo_returns_parsed_json(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sub": "abc123", "name": "Founder"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    result = await client.userinfo()

    assert result == {"sub": "abc123", "name": "Founder"}


@pytest.mark.asyncio
async def test_userinfo_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid access token"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="expired")
    with pytest.raises(LinkedInAPIError, match="Invalid access token"):
        await client.userinfo()


@pytest.mark.asyncio
async def test_raises_on_network_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    with pytest.raises(LinkedInAPIError):
        await client.userinfo()


@pytest.mark.asyncio
async def test_raises_on_non_json_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    with pytest.raises(LinkedInAPIError):
        await client.userinfo()


@pytest.mark.asyncio
async def test_create_post_sends_expected_headers_and_body(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    result = await client.create_post(person_id="abc123", text="Great point!", visibility="PUBLIC")

    assert captured["headers"]["linkedin-version"] == "202401"
    assert captured["headers"]["x-restli-protocol-version"] == "2.0.0"
    assert captured["body"]["author"] == "urn:li:person:abc123"
    assert captured["body"]["commentary"] == "Great point!"
    assert captured["body"]["visibility"] == "PUBLIC"
    assert result["id"] == "urn:li:share:999"


@pytest.mark.asyncio
async def test_create_post_reads_id_from_body_when_present(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "urn:li:share:from-body"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    result = await client.create_post(person_id="abc123", text="hi", visibility="PUBLIC")

    assert result["id"] == "urn:li:share:from-body"


@pytest.mark.asyncio
async def test_create_post_returns_none_id_when_no_body_or_header(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201)

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    result = await client.create_post(person_id="abc123", text="hi", visibility="PUBLIC")

    assert result["id"] is None


@pytest.mark.asyncio
async def test_create_post_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "commentary exceeds max length"})

    _patch_async_client(monkeypatch, handler)
    client = LinkedInClient(access_token="at")
    with pytest.raises(LinkedInAPIError, match="exceeds max length"):
        await client.create_post(person_id="abc123", text="x" * 5000, visibility="PUBLIC")
