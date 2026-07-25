"""See docs/auth/OAUTH2_ARCHITECTURE.md §1 and app/core/oauth/client.py. Uses httpx's
MockTransport so this is a real HTTP round trip through the client (headers, body encoding,
status handling) without ever reaching the network."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from plugins._shared.oauth import OAuthProviderSpec

from app.core.oauth.client import OAuthClient
from app.core.oauth.errors import PermanentRefreshFailure, TokenExchangeFailed

SPEC = OAuthProviderSpec(
    authorize_url="https://provider.invalid/authorize",
    token_url="https://provider.invalid/token",
    revoke_url="https://provider.invalid/revoke",
    scopes=("read", "submit"),
)


def _client() -> OAuthClient:
    return OAuthClient(
        client_id="test-client-id", client_secret="test-client-secret", redirect_uri="https://growthos.invalid/cb"
    )


def test_build_authorize_url_includes_required_params() -> None:
    client = _client()
    url = client.build_authorize_url(SPEC, state="the-state")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == SPEC.authorize_url
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test-client-id"]
    assert params["redirect_uri"] == ["https://growthos.invalid/cb"]
    assert params["scope"] == ["read submit"]
    assert params["state"] == ["the-state"]
    assert "code_challenge" not in params


def test_build_authorize_url_includes_pkce_challenge_when_provided() -> None:
    client = _client()
    url = client.build_authorize_url(SPEC, state="s", code_challenge="the-challenge")
    params = parse_qs(urlparse(url).query)
    assert params["code_challenge"] == ["the-challenge"]
    assert params["code_challenge_method"] == ["S256"]


def test_build_authorize_url_includes_extra_authorize_params() -> None:
    spec = OAuthProviderSpec(
        authorize_url=SPEC.authorize_url,
        token_url=SPEC.token_url,
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
    )
    url = _client().build_authorize_url(spec, state="s")
    params = parse_qs(urlparse(url).query)
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]


@pytest.mark.asyncio
async def test_exchange_code_success(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = parse_qs(request.content.decode())
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "access_token": "at-123",
                "refresh_token": "rt-456",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "read submit",
            },
        )

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    result = await client.exchange_code(SPEC, code="the-code")

    assert result.access_token == "at-123"
    assert result.refresh_token == "rt-456"
    assert result.token_type == "bearer"
    assert result.granted_scopes == ("read", "submit")
    assert captured["url"] == SPEC.token_url
    assert captured["body"]["grant_type"] == ["authorization_code"]
    assert captured["body"]["code"] == ["the-code"]
    assert captured["auth_header"] is not None and captured["auth_header"].startswith("Basic ")


@pytest.mark.asyncio
async def test_exchange_code_sends_extra_token_headers(monkeypatch) -> None:
    """Discovered implementing Reddit (docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md):
    some providers require specific headers (e.g. User-Agent) on the token endpoint itself,
    not just the data API — extra_token_headers exists for exactly this."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"access_token": "at", "expires_in": 60})

    _patch_async_client(monkeypatch, handler)
    spec = OAuthProviderSpec(
        authorize_url=SPEC.authorize_url,
        token_url=SPEC.token_url,
        extra_token_headers={"User-Agent": "growthos:reddit:v1.0 (test)"},
    )
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.exchange_code(spec, code="c")

    assert captured["user_agent"] == "growthos:reddit:v1.0 (test)"


@pytest.mark.asyncio
async def test_exchange_code_with_pkce_verifier(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(200, json={"access_token": "at", "expires_in": 60})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.exchange_code(SPEC, code="c", code_verifier="the-verifier")

    assert captured["body"]["code_verifier"] == ["the-verifier"]


@pytest.mark.asyncio
async def test_exchange_code_defaults_granted_scopes_to_requested_when_provider_omits_scope(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at", "expires_in": 60})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    result = await client.exchange_code(SPEC, code="c")

    assert result.granted_scopes == SPEC.scopes


@pytest.mark.asyncio
async def test_client_secret_post_puts_credentials_in_body_not_header(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = parse_qs(request.content.decode())
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200, json={"access_token": "at", "expires_in": 60})

    _patch_async_client(monkeypatch, handler)
    spec = OAuthProviderSpec(
        authorize_url=SPEC.authorize_url,
        token_url=SPEC.token_url,
        token_endpoint_auth_method="client_secret_post",
    )
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.exchange_code(spec, code="c")

    assert captured["auth_header"] is None
    assert captured["body"]["client_id"] == ["id"]
    assert captured["body"]["client_secret"] == ["secret"]


@pytest.mark.asyncio
async def test_token_endpoint_error_raises_token_exchange_failed(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_request"})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    with pytest.raises(TokenExchangeFailed) as exc_info:
        await client.exchange_code(SPEC, code="c")
    assert exc_info.value.provider_error == "invalid_request"


@pytest.mark.asyncio
async def test_missing_access_token_raises_token_exchange_failed(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "bearer"})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    with pytest.raises(TokenExchangeFailed):
        await client.exchange_code(SPEC, code="c")


@pytest.mark.asyncio
async def test_network_error_raises_token_exchange_failed(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    with pytest.raises(TokenExchangeFailed):
        await client.exchange_code(SPEC, code="c")


@pytest.mark.asyncio
async def test_refresh_with_invalid_grant_raises_permanent_refresh_failure(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    with pytest.raises(PermanentRefreshFailure):
        await client.refresh(SPEC, refresh_token="rt")


@pytest.mark.asyncio
async def test_refresh_with_transient_error_raises_base_token_exchange_failed_not_permanent(
    monkeypatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "temporarily_unavailable"})

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    with pytest.raises(TokenExchangeFailed) as exc_info:
        await client.refresh(SPEC, refresh_token="rt")
    assert not isinstance(exc_info.value, PermanentRefreshFailure)


@pytest.mark.asyncio
async def test_revoke_posts_token_and_never_raises_on_failure(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patch_async_client(monkeypatch, handler)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.revoke(SPEC, token="at")  # must not raise


@pytest.mark.asyncio
async def test_revoke_sends_extra_token_headers(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(200)

    _patch_async_client(monkeypatch, handler)
    spec = OAuthProviderSpec(
        authorize_url=SPEC.authorize_url,
        token_url=SPEC.token_url,
        revoke_url=SPEC.revoke_url,
        extra_token_headers={"User-Agent": "growthos:reddit:v1.0 (test)"},
    )
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.revoke(spec, token="at")

    assert captured["user_agent"] == "growthos:reddit:v1.0 (test)"


@pytest.mark.asyncio
async def test_revoke_is_a_noop_when_no_revoke_url_declared(monkeypatch) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    _patch_async_client(monkeypatch, handler)
    spec = OAuthProviderSpec(authorize_url=SPEC.authorize_url, token_url=SPEC.token_url, revoke_url=None)
    client = OAuthClient(client_id="id", client_secret="secret", redirect_uri="https://growthos.invalid/cb")
    await client.revoke(spec, token="at")
    assert called is False


def _patch_async_client(monkeypatch, handler) -> None:
    """Redirects every httpx.AsyncClient constructed inside app.core.oauth.client to use a
    MockTransport, so exchange_code/refresh/revoke exercise real request-building and
    response-parsing code without any network access."""
    import app.core.oauth.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)
