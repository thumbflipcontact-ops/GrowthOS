"""See app/core/webhooks/client.py. Uses httpx's MockTransport, same technique
test_resend_client.py/test_oauth_client.py use.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.webhooks.client import WebhookHttpClient
from app.core.webhooks.errors import WebhookDeliveryFailed


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler):
    import app.core.webhooks.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_send_returns_status_code_on_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)
    client = WebhookHttpClient()

    status_code = await client.send(
        url="https://hooks.example.com/x", headers={"X-Test": "1"}, body=b"{}"
    )
    assert status_code == 200


@pytest.mark.asyncio
async def test_send_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    _patch_transport(monkeypatch, handler)
    client = WebhookHttpClient()

    with pytest.raises(WebhookDeliveryFailed):
        await client.send(url="https://hooks.example.com/x", headers={}, body=b"{}")


@pytest.mark.asyncio
async def test_send_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    client = WebhookHttpClient()

    with pytest.raises(WebhookDeliveryFailed):
        await client.send(url="https://hooks.example.com/x", headers={}, body=b"{}")
