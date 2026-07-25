"""Unit tests for RedditPlugin — see plugins/reddit/plugin.py. Uses a fake RedditClient (not
httpx.MockTransport — see test_client.py for HTTP-level coverage) so these tests focus on
RedditPlugin's own logic: subreddit iteration, since-filtering, rate limiting, error
isolation, and credential-absence handling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

import plugins.reddit.plugin as plugin_module
from plugins._shared.base import PluginQuery, ResolvedConnection
from plugins._shared.credentials import ApiKeyCredentials, OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.reddit.client import RedditAPIError
from plugins.reddit.plugin import RedditPlugin, create_plugin


def _oauth_connection(
    *, subreddits: list[str] | None = None, label: str = "default"
) -> ResolvedConnection:
    return ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="reddit",
        label=label,
        config={"subreddits": subreddits if subreddits is not None else ["SEO"]},
        credentials=OAuth2Credentials(
            access_token="at-123",
            refresh_token="rt-456",
            token_type="bearer",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            granted_scopes=("read", "submit", "identity"),
        ),
    )


@dataclass
class _FakeContentItem:
    target_ref: str | None
    body: str | None


@dataclass
class _FakeRedditClient:
    """Test double for RedditClient — queued responses per method, so tests control exactly
    what "Reddit" returns without any HTTP layer involved."""

    search_results: dict[str, list[dict]] = field(default_factory=dict)
    search_raises: set[str] = field(default_factory=set)
    submit_response: dict | None = None
    submit_error: RedditAPIError | None = None
    me_response: dict | None = None
    me_error: RedditAPIError | None = None
    submit_calls: list[tuple[str, str]] = field(default_factory=list)
    search_calls: list[tuple[str, str, int]] = field(default_factory=list)

    async def search_subreddit(self, subreddit: str, query: str, *, limit: int) -> list[dict]:
        self.search_calls.append((subreddit, query, limit))
        if subreddit in self.search_raises:
            raise RedditAPIError(f"boom in {subreddit}")
        return self.search_results.get(subreddit, [])

    async def submit_comment(self, *, thing_id: str, text: str) -> dict:
        self.submit_calls.append((thing_id, text))
        if self.submit_error is not None:
            raise self.submit_error
        return self.submit_response or {}

    async def me(self) -> dict:
        if self.me_error is not None:
            raise self.me_error
        return self.me_response or {}


def _install_fake_client(monkeypatch, fake: _FakeRedditClient) -> None:
    """RedditPlugin.__init__ builds its client via _build_client(), which constructs a real
    RedditClient — patched here to hand back our fake instead, keeping these tests focused on
    RedditPlugin's own logic."""
    monkeypatch.setattr(plugin_module, "_build_client", lambda connection: fake)


def _post(
    *, name: str = "t3_a", title: str = "Post", permalink: str = "/r/SEO/x/", **extra
) -> dict:
    return {"name": name, "title": title, "permalink": permalink, **extra}


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch):
    """The module-level rate limiter persists across calls by design (see plugin.py) — reset
    it to a fresh, generous instance for each test so tests don't interfere with each
    other's budgets."""
    monkeypatch.setattr(
        plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1000, refill_rate=1000.0)
    )


@pytest.mark.asyncio
async def test_search_returns_results_from_configured_subreddits(monkeypatch) -> None:
    fake = _FakeRedditClient(search_results={"SEO": [_post(name="t3_a", title="Hello")]})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO"]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing"]))

    assert len(results) == 1
    assert results[0].title == "Hello"
    assert results[0].url == "https://reddit.com/r/SEO/x/"
    assert results[0].platform_metadata["subreddit"] == "SEO"
    assert results[0].platform_metadata["thing_id"] == "t3_a"
    assert fake.search_calls == [("SEO", "indexing", 25)]


@pytest.mark.asyncio
async def test_search_joins_multiple_terms_with_or(monkeypatch) -> None:
    fake = _FakeRedditClient(search_results={"SEO": []})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO"]))
    await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["indexing", "crawl budget"]))

    assert fake.search_calls[0][1] == "indexing OR crawl budget"


@pytest.mark.asyncio
async def test_search_queries_every_configured_subreddit(monkeypatch) -> None:
    fake = _FakeRedditClient(
        search_results={
            "SEO": [_post(name="t3_a")],
            "juststart": [_post(name="t3_b")],
        }
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO", "juststart"]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"], limit=25))

    assert {r.platform_metadata["thing_id"] for r in results} == {"t3_a", "t3_b"}


@pytest.mark.asyncio
async def test_search_respects_limit_across_subreddits(monkeypatch) -> None:
    fake = _FakeRedditClient(
        search_results={
            "SEO": [_post(name="t3_a"), _post(name="t3_b")],
            "juststart": [_post(name="t3_c")],
        }
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO", "juststart"]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"], limit=2))

    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_returns_empty_with_no_subreddits_configured(monkeypatch) -> None:
    fake = _FakeRedditClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=[]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []
    assert fake.search_calls == []  # never even calls Reddit


@pytest.mark.asyncio
async def test_search_one_failing_subreddit_does_not_fail_the_whole_search(monkeypatch) -> None:
    fake = _FakeRedditClient(
        search_results={"juststart": [_post(name="t3_ok")]}, search_raises={"SEO"}
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO", "juststart"]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert len(results) == 1
    assert results[0].platform_metadata["thing_id"] == "t3_ok"


@pytest.mark.asyncio
async def test_search_filters_out_posts_older_than_since(monkeypatch) -> None:
    now = datetime.now(UTC)
    old_post = _post(name="t3_old", created_utc=(now - timedelta(days=10)).timestamp())
    new_post = _post(name="t3_new", created_utc=now.timestamp())
    fake = _FakeRedditClient(search_results={"SEO": [old_post, new_post]})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO"]))
    results = await plugin.search(
        PluginQuery(project_id=uuid.uuid4(), terms=["x"], since=now - timedelta(days=1))
    )

    assert [r.platform_metadata["thing_id"] for r in results] == ["t3_new"]


@pytest.mark.asyncio
async def test_search_returns_empty_without_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="reddit",
        label="default",
        config={"subreddits": ["SEO"]},
        credentials=None,
    )
    plugin = create_plugin(connection)  # real _build_client() — not patched — sees credentials=None
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []


@pytest.mark.asyncio
async def test_search_returns_empty_with_non_oauth_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(),
        plugin_key="reddit",
        label="default",
        config={"subreddits": ["SEO"]},
        credentials=ApiKeyCredentials(api_key="wrong-shape-for-reddit"),
    )
    plugin = create_plugin(connection)
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    assert results == []


@pytest.mark.asyncio
async def test_search_stops_when_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1, refill_rate=0.0001))
    fake = _FakeRedditClient(search_results={"SEO": [_post()], "juststart": [_post()]})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection(subreddits=["SEO", "juststart"]))
    results = await plugin.search(PluginQuery(project_id=uuid.uuid4(), terms=["x"]))

    # Exactly one subreddit's worth of budget was available — the search stops rather than
    # raising, per the documented rate-limit contract.
    assert len(fake.search_calls) == 1
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_publish_success(monkeypatch) -> None:
    fake = _FakeRedditClient(
        submit_response={
            "json": {"data": {"things": [{"data": {"permalink": "/r/SEO/comments/x/y/"}}]}}
        }
    )
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref="t3_abc123", body="Great point!"))

    assert result.success is True
    assert result.published_url == "https://reddit.com/r/SEO/comments/x/y/"
    assert result.error is None
    assert fake.submit_calls == [("t3_abc123", "Great point!")]


@pytest.mark.asyncio
async def test_publish_success_with_unparseable_response_still_reports_success(monkeypatch) -> None:
    fake = _FakeRedditClient(submit_response={"json": {"data": {"things": []}}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref="t3_abc123", body="hi"))

    assert result.success is True
    assert result.published_url is None  # couldn't extract a permalink, but the post succeeded


@pytest.mark.asyncio
async def test_publish_surfaces_reddit_api_error_verbatim(monkeypatch) -> None:
    fake = _FakeRedditClient(submit_error=RedditAPIError("Reddit rejected the request: RATELIMIT"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref="t3_abc123", body="hi"))

    assert result.success is False
    assert result.published_url is None
    assert "RATELIMIT" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_rejects_item_missing_target_ref(monkeypatch) -> None:
    fake = _FakeRedditClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref=None, body="hi"))

    assert result.success is False
    assert fake.submit_calls == []  # never even called Reddit


@pytest.mark.asyncio
async def test_publish_rejects_item_missing_body(monkeypatch) -> None:
    fake = _FakeRedditClient()
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    result = await plugin.publish(_FakeContentItem(target_ref="t3_abc", body=None))

    assert result.success is False
    assert fake.submit_calls == []


@pytest.mark.asyncio
async def test_publish_without_credentials_fails_clearly(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="reddit", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    result = await plugin.publish(_FakeContentItem(target_ref="t3_abc", body="hi"))

    assert result.success is False
    assert "credentials" in (result.error or "")


@pytest.mark.asyncio
async def test_publish_stops_when_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "_RATE_LIMITER", RateLimiter(capacity=1, refill_rate=0.0001))
    fake = _FakeRedditClient(submit_response={"json": {"data": {"things": []}}})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    first = await plugin.publish(_FakeContentItem(target_ref="t3_a", body="one"))
    second = await plugin.publish(_FakeContentItem(target_ref="t3_b", body="two"))

    assert first.success is True
    assert second.success is False
    assert "Rate limited" in (second.error or "")


@pytest.mark.asyncio
async def test_health_check_true_when_reddit_responds(monkeypatch) -> None:
    fake = _FakeRedditClient(me_response={"name": "growthos-bot"})
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_on_api_error(monkeypatch) -> None:
    fake = _FakeRedditClient(me_error=RedditAPIError("token invalid"))
    _install_fake_client(monkeypatch, fake)

    plugin = create_plugin(_oauth_connection())
    assert await plugin.health_check() is False


@pytest.mark.asyncio
async def test_health_check_false_without_credentials(monkeypatch) -> None:
    connection = ResolvedConnection(
        project_id=uuid.uuid4(), plugin_key="reddit", label="default", config={}, credentials=None
    )
    plugin = create_plugin(connection)
    assert await plugin.health_check() is False


def test_create_plugin_returns_a_reddit_plugin() -> None:
    plugin = create_plugin(_oauth_connection())
    assert isinstance(plugin, RedditPlugin)
    assert plugin.manifest.key == "reddit"
