"""Unit tests for TwitterPlugin — see plugins/twitter/plugin.py. Uses a fake TwitterClient
(not httpx.MockTransport — see test_client.py for HTTP-level coverage) so these tests focus
on TwitterPlugin's own logic: query building, since-filtering, rate limiting, and
credential-absence handling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

import plugins.twitter.plugin as plugin_module
from plugins._shared.base import PluginQuery, ResolvedConnection
from plugins._shared.credentials import ApiKeyCredentials, OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.twitter.client import TwitterAPIError
from plugins.twitter.plugin import TwitterPlugin, create_plugin


def _oauth_connection(*, config: dict | None = None, label: str = "default") -> ResolvedConnection:
    return ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="twitter",
        label=label,
        config=config if config is not None else {},
        credentials=OAuth2Credentials(
            access_token="at-123",
            refresh_token="rt-456",
            token_type="bearer",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            granted_scopes=("tweet.read", "tweet.write", "users.read", "offline.access"),
        ),
    )


@dataclass
class _FakeContentItem:
    target_ref: str | None
    body: str | None


@dataclass
class _FakeTwitterClient:
    """Test double for TwitterClient — queued responses per method, so tests control exactly
    what "X" returns without any HTTP layer involved."""

    search_response: dict | None = None
    search_raises: TwitterAPIError | None = None
    create_response: dict | None = None
    create_error: TwitterAPIError | None = None
    me_response: dict | None = None
    me_error: TwitterAPIError | None = None
    create_calls: list[tuple[str, str | None]] = field(default_factory=list)
    search_calls: list[tuple[str, int]] = field(default_factory=list)

    async def search_recent(self, query: str, *, max_results: int) -> dict:
        self.search_calls.append((query, max_results))
        if self.search_raises is not None:
            raise self.search_raises
        return self.search_response or {"data": []}

    async def create_tweet(self, *, text: str, reply_to_tweet_id: str | None = None) -> dict:
        self.create_calls.append((text, reply_to_tweet_id))
        if self.create_error is not None:
            raise self.create_error
        return self.create_response or {}

    async def me(self) -> dict:
        if self.me_error is not None:
            raise self.me_error
        return self.me_response or {}


def _install_fake_client(monkeypatch, fake: _FakeTwitterClient) -> None:
    """TwitterPlugin.__init__ builds its client via _build_client(), which constructs a real
    TwitterClient — patched here to hand back our fake instead, keeping these tests focused
    on TwitterPlugin's own logic."""
    monkeypatch.setattr(plugin_module, "_build_client", lambda connection: fake)


def _tweet(*, id: str = "1", text: str = "hello", author_id: str = "u1", **extra) -> dict:
    return {"id": id, "text": text, "author_id": author_id, **extra}


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch):
    """The module-level rate limiter persists across calls by design (see plugin.py) — reset
    it to a fresh, generous instance for each test so tests don't interfere with each
    other's budgets."""
    monkeypatch.setattr(
        plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1000, refill_rate=1000.0)
    )


@pytest.mark.asyncio
async def test_search_returns_results(monkeypatch) -> None:
    fake = _FakeTwitterClient(
        search_response={
            "data": [_tweet(id="1", text="Hello", author_id="u1")],
            "includes": {"users": [{"id": "u1", "username": "founder"}]},
        }
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing"]))

    assert len(results) == 1
    assert results[0].body == "Hello"
    assert results[0].author == "founder"
    assert results[0].platform_metadata["tweet_id"] == "1"


@pytest.mark.asyncio
async def test_search_joins_multiple_terms_with_or_and_parens(monkeypatch) -> None:
    fake = _FakeTwitterClient(search_response={"data": []})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing", "crawl budget"]))

    assert fake.search_calls[0][0] == "(indexing OR crawl budget) -is:retweet"


@pytest.mark.asyncio
async def test_search_single_term_has_no_parens(monkeypatch) -> None:
    fake = _FakeTwitterClient(search_response={"data": []})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing"]))

    assert fake.search_calls[0][0] == "indexing -is:retweet"


@pytest.mark.asyncio
async def test_search_applies_config_filters(monkeypatch) -> None:
    fake = _FakeTwitterClient(search_response={"data": []})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(
        _oauth_connection(config={"exclude_retweets": False, "exclude_replies": True, "lang": "en"})
    )
    await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing"]))

    assert fake.search_calls[0][0] == "indexing -is:reply lang:en"


@pytest.mark.asyncio
async def test_search_returns_empty_with_no_terms(monkeypatch) -> None:
    fake = _FakeTwitterClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=[]))

    assert results == []
    assert fake.search_calls == []  # never even calls X


@pytest.mark.asyncio
async def test_search_one_api_error_returns_empty_not_raises(monkeypatch) -> None:
    fake = _FakeTwitterClient(search_raises=TwitterAPIError("boom"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []


@pytest.mark.asyncio
async def test_search_filters_out_tweets_older_than_since(monkeypatch) -> None:
    now = datetime.now(UTC)
    old_tweet = _tweet(id="old", created_at=(now - timedelta(days=10)).isoformat())
    new_tweet = _tweet(id="new", created_at=now.isoformat())
    fake = _FakeTwitterClient(search_response={"data": [old_tweet, new_tweet]})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    results = await plugin.search(
        PluginQuery(project_id=uuid.uuid4(), terms=["x"], since=now - timedelta(days=1))
    )

    assert [r.platform_metadata["tweet_id"] for r in results] == ["new"]


@pytest.mark.asyncio
async def test_search_respects_limit(monkeypatch) -> None:
    fake = _FakeTwitterClient(
        search_response={"data": [_tweet(id="1"), _tweet(id="2"), _tweet(id="3")]}
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"], limit=2))

    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_returns_empty_without_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="twitter", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)  # real _build_client() — not patched — sees credentials=None
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []


@pytest.mark.asyncio
async def test_search_returns_empty_with_non_oauth_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="twitter",
        label="default",
        config={},
        credentials=ApiKeyCredentials(api_key="wrong-shape-for-twitter"),
    )
    plugin = create_plugin(connection)
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []


@pytest.mark.asyncio
async def test_search_stops_when_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1, refill_rate=0.0001))
    fake = _FakeTwitterClient(search_response={"data": [_tweet()]})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    first = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))
    second = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert len(first) == 1
    assert second == []  # throttled — never raises, per RateLimiter's documented contract


@pytest.mark.asyncio
async def test_publish_success(monkeypatch) -> None:
    fake = _FakeTwitterClient(create_response={"data": {"id": "999", "text": "Great point!"}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref=None, body="Great point!"))

    assert result.success is True
    assert result.published_url == "https://twitter.com/i/web/status/999"
    assert result.error is None
    assert fake.create_calls == [("Great point!", None)]


@pytest.mark.asyncio
async def test_publish_as_reply_passes_target_ref(monkeypatch) -> None:
    fake = _FakeTwitterClient(create_response={"data": {"id": "1000", "text": "reply"}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    await plugin.publish(_FakeContentItem(target_ref="123", body="reply"))

    assert fake.create_calls == [("reply", "123")]


@pytest.mark.asyncio
async def test_publish_surfaces_api_error_verbatim(monkeypatch) -> None:
    fake = _FakeTwitterClient(create_error=TwitterAPIError("X returned 403: Forbidden"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref=None, body="hi"))

    assert result.success is False
    assert result.published_url is None
    assert "Forbidden" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_rejects_item_missing_body(monkeypatch) -> None:
    fake = _FakeTwitterClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref=None, body=None))

    assert result.success is False
    assert fake.create_calls == []  # never even called X


@pytest.mark.asyncio
async def test_publish_without_credentials_fails_clearly(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="twitter", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    result = await plugin.publish(_FakeContentItem(target_ref=None, body="hi"))

    assert result.success is False
    assert "credentials" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_stops_when_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1, refill_rate=0.0001))
    fake = _FakeTwitterClient(create_response={"data": {"id": "1"}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    first = await plugin.publish(_FakeContentItem(target_ref=None, body="one"))
    second = await plugin.publish(_FakeContentItem(target_ref=None, body="two"))

    assert first.success is True
    assert second.success is False
    assert "Rate limited" in (second.error or "")


@pytest.mark.asyncio
async def test_health_check_true_when_x_responds(monkeypatch) -> None:
    fake = _FakeTwitterClient(me_response={"data": {"id": "1", "username": "growthos_bot"}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_on_api_error(monkeypatch) -> None:
    fake = _FakeTwitterClient(me_error=TwitterAPIError("token invalid"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is False


@pytest.mark.asyncio
async def test_health_check_false_without_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="twitter", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    assert await plugin.health_check() is False


def test_create_plugin_returns_a_twitter_plugin() -> None:
    plugin = create_plugin(_oauth_connection())
    assert isinstance(plugin, TwitterPlugin)
    assert plugin.manifest.key == "twitter"
