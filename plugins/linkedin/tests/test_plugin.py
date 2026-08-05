"""Unit tests for LinkedInPlugin — see plugins/linkedin/plugin.py. Uses a fake LinkedInClient
(not httpx.MockTransport — see test_client.py for HTTP-level coverage) so these tests focus
on LinkedInPlugin's own logic: the userinfo->create_post two-step flow, rate limiting, and
credential-absence handling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

import plugins.linkedin.plugin as plugin_module
from plugins._shared.base import ResolvedConnection
from plugins._shared.credentials import ApiKeyCredentials, OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.linkedin.client import LinkedInAPIError
from plugins.linkedin.plugin import LinkedInPlugin, create_plugin


def _oauth_connection(*, config: dict | None = None, label: str = "default") -> ResolvedConnection:
    return ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="linkedin",
        label=label,
        config=config if config is not None else {},
        credentials=OAuth2Credentials(
            access_token="at-123",
            refresh_token=None,
            token_type="bearer",
            expires_at=datetime.now(UTC) + timedelta(days=60),
            granted_scopes=("openid", "profile", "w_member_social"),
        ),
    )


@dataclass
class _FakeContentItem:
    body: str | None


@dataclass
class _FakeLinkedInClient:
    """Test double for LinkedInClient — queued responses per method, so tests control
    exactly what "LinkedIn" returns without any HTTP layer involved."""

    userinfo_response: dict | None = None
    userinfo_error: LinkedInAPIError | None = None
    create_post_response: dict | None = None
    create_post_error: LinkedInAPIError | None = None
    create_post_calls: list[tuple[str, str, str]] = field(default_factory=list)

    async def userinfo(self) -> dict:
        if self.userinfo_error is not None:
            raise self.userinfo_error
        return self.userinfo_response if self.userinfo_response is not None else {"sub": "abc123"}

    async def create_post(self, *, person_id: str, text: str, visibility: str) -> dict:
        self.create_post_calls.append((person_id, text, visibility))
        if self.create_post_error is not None:
            raise self.create_post_error
        return self.create_post_response or {"id": None}


def _install_fake_client(monkeypatch, fake: _FakeLinkedInClient) -> None:
    """LinkedInPlugin.__init__ builds its client via _build_client(), which constructs a real
    LinkedInClient — patched here to hand back our fake instead, keeping these tests focused
    on LinkedInPlugin's own logic."""
    monkeypatch.setattr(plugin_module, "_build_client", lambda connection: fake)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch):
    """The module-level rate limiter persists across calls by design (see plugin.py) — reset
    it to a fresh, generous instance for each test so tests don't interfere with each
    other's budgets."""
    monkeypatch.setattr(
        plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1000, refill_rate=1000.0)
    )


@pytest.mark.asyncio
async def test_publish_success(monkeypatch) -> None:
    fake = _FakeLinkedInClient(
        userinfo_response={"sub": "abc123"},
        create_post_response={"id": "urn:li:share:999"},
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body="Great point!"))

    assert result.success is True
    assert result.published_url == "https://www.linkedin.com/feed/update/urn:li:share:999/"
    assert result.error is None
    assert fake.create_post_calls == [("abc123", "Great point!", "PUBLIC")]


@pytest.mark.asyncio
async def test_publish_uses_configured_visibility(monkeypatch) -> None:
    fake = _FakeLinkedInClient(create_post_response={"id": "urn:li:share:1"})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(config={"visibility": "CONNECTIONS"}))
    await plugin.publish(_FakeContentItem(body="hi"))

    assert fake.create_post_calls == [("abc123", "hi", "CONNECTIONS")]


@pytest.mark.asyncio
async def test_publish_success_with_no_id_still_reports_success(monkeypatch) -> None:
    fake = _FakeLinkedInClient(create_post_response={"id": None})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is True
    assert result.published_url is None  # couldn't extract an id, but the post succeeded


@pytest.mark.asyncio
async def test_publish_fails_when_userinfo_has_no_sub(monkeypatch) -> None:
    fake = _FakeLinkedInClient(userinfo_response={"name": "Founder"})  # missing "sub"
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is False
    assert "member id" in (result.error or "")
    assert fake.create_post_calls == []  # never even reached create_post


@pytest.mark.asyncio
async def test_publish_surfaces_userinfo_api_error_verbatim(monkeypatch) -> None:
    fake = _FakeLinkedInClient(
        userinfo_error=LinkedInAPIError("LinkedIn returned 401: token expired")
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is False
    assert "token expired" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_surfaces_create_post_api_error_verbatim(monkeypatch) -> None:
    fake = _FakeLinkedInClient(
        create_post_error=LinkedInAPIError("LinkedIn returned 422: commentary exceeds max length")
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is False
    assert result.published_url is None
    assert "exceeds max length" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_rejects_item_missing_body(monkeypatch) -> None:
    fake = _FakeLinkedInClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(body=None))

    assert result.success is False
    assert fake.create_post_calls == []  # never even called LinkedIn


@pytest.mark.asyncio
async def test_publish_without_credentials_fails_clearly(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="linkedin", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is False
    assert "credentials" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_returns_empty_with_non_oauth_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="linkedin",
        label="default",
        config={},
        credentials=ApiKeyCredentials(api_key="wrong-shape-for-linkedin"),
    )
    plugin = create_plugin(connection)
    result = await plugin.publish(_FakeContentItem(body="hi"))

    assert result.success is False
    assert "credentials" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_stops_when_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1, refill_rate=0.0001))
    fake = _FakeLinkedInClient(create_post_response={"id": "urn:li:share:1"})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    first = await plugin.publish(_FakeContentItem(body="one"))
    second = await plugin.publish(_FakeContentItem(body="two"))

    assert first.success is True
    assert second.success is False
    assert "Rate limited" in (second.error or "")


@pytest.mark.asyncio
async def test_health_check_true_when_linkedin_responds(monkeypatch) -> None:
    fake = _FakeLinkedInClient(userinfo_response={"sub": "abc123"})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_on_api_error(monkeypatch) -> None:
    fake = _FakeLinkedInClient(userinfo_error=LinkedInAPIError("token invalid"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is False


@pytest.mark.asyncio
async def test_health_check_false_without_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="linkedin", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    assert await plugin.health_check() is False


def test_create_plugin_returns_a_linkedin_plugin() -> None:
    plugin = create_plugin(_oauth_connection())
    assert isinstance(plugin, LinkedInPlugin)
    assert plugin.manifest.key == "linkedin"
