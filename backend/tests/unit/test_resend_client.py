"""See app/core/email/client.py. Uses httpx's MockTransport so this is a real HTTP round trip
through the client (headers, body encoding, status handling) without ever reaching the network
— same technique test_oauth_client.py uses for OAuthClient.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.email.client import ResendClient
from app.core.email.errors import EmailNotConfigured, EmailSendFailed


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler):
    import app.core.email.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_send_posts_expected_payload_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["body"] = request.content
        return httpx.Response(200, json={"id": "email_123"})

    _patch_transport(monkeypatch, handler)
    client = ResendClient(api_key="re_test", from_email="Threadly <notifications@usethreadly.co>")

    await client.send(to="user@example.com", subject="Hi", html_body="<p>hi</p>")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test"
    import json as _json

    body = _json.loads(captured["body"])
    assert body["to"] == ["user@example.com"]
    assert body["subject"] == "Hi"
    assert body["from"] == "Threadly <notifications@usethreadly.co>"


@pytest.mark.asyncio
async def test_send_raises_email_send_failed_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from address"})

    _patch_transport(monkeypatch, handler)
    client = ResendClient(api_key="re_test", from_email="notifications@usethreadly.co")

    with pytest.raises(EmailSendFailed):
        await client.send(to="user@example.com", subject="Hi", html_body="<p>hi</p>")


@pytest.mark.asyncio
async def test_send_raises_email_send_failed_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    client = ResendClient(api_key="re_test", from_email="notifications@usethreadly.co")

    with pytest.raises(EmailSendFailed):
        await client.send(to="user@example.com", subject="Hi", html_body="<p>hi</p>")


def test_from_settings_raises_email_not_configured_when_unset() -> None:
    from app.core.config import Settings

    settings = Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
    )

    with pytest.raises(EmailNotConfigured):
        ResendClient.from_settings(settings)


def test_from_settings_builds_a_client_when_configured() -> None:
    from app.core.config import Settings

    settings = Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
        resend_api_key="re_test",
        resend_from_email="notifications@usethreadly.co",
    )

    client = ResendClient.from_settings(settings)

    assert client.api_key == "re_test"
    assert client.from_email == "notifications@usethreadly.co"
