"""End-to-end tests for ConversationFinderAgent.run() against a mocked plugin registry,
knowledge base, and event publisher — see docs/agents/AGENT_ARCHITECTURE.md §Testing ("every
agent's test suite runs against a mocked PluginRegistry ... and a mocked/recorded
LLMProvider response" — Phase 2A has no LLM, so no LLM double is needed here).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

from agents._shared.base import AgentContext
from agents.conversation_finder.agent import AGENT, ConversationFinderAgent
from plugins._shared.base import PluginQuery, PluginResult


@dataclass
class _FakePlugin:
    key: str
    results: list[PluginResult] = field(default_factory=list)
    raises: bool = False
    calls: list[PluginQuery] = field(default_factory=list)

    @property
    def manifest(self) -> SimpleNamespace:
        return SimpleNamespace(key=self.key)

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        self.calls.append(query)
        if self.raises:
            raise RuntimeError("plugin blew up")
        return self.results


class _FakeRegistry:
    def __init__(self, plugins: list[_FakePlugin]) -> None:
        self._plugins = plugins

    def all_with_capability(self, required: type) -> list[_FakePlugin]:
        return self._plugins


@dataclass
class _FakeKnowledgeBase:
    existing_urls: set[str] = field(default_factory=set)
    saved_calls: list[dict[str, Any]] = field(default_factory=list)

    async def upsert_discovery(
        self,
        *,
        project_id: uuid.UUID,
        source_agent_run_id: uuid.UUID | None,
        platform: str,
        url: str,
        tags: list[str],
        confidence: Decimal,
        title: str | None = None,
        body_excerpt: str | None = None,
        platform_metadata: dict[str, Any] | None = None,
    ) -> tuple[SimpleNamespace, bool]:
        created = url not in self.existing_urls
        self.existing_urls.add(url)
        self.saved_calls.append(
            {
                "platform": platform,
                "url": url,
                "tags": tags,
                "confidence": confidence,
                "title": title,
                "body_excerpt": body_excerpt,
                "platform_metadata": platform_metadata,
            }
        )
        item = SimpleNamespace(
            id=uuid.uuid4(),
            project_id=project_id,
            platform=platform,
            url=url,
            tags=tags,
            confidence=confidence,
            buying_intent=SimpleNamespace(value="none"),
        )
        return item, created


@dataclass
class _FakeEventPublisher:
    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(
        self, *, project_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.published.append(
            {"project_id": project_id, "event_type": event_type, "payload": payload}
        )


def _project(icp_keywords: list[str] | None = None) -> SimpleNamespace:
    icp_config = {"keywords": icp_keywords} if icp_keywords is not None else {}
    return SimpleNamespace(id=uuid.uuid4(), icp_config=icp_config)


def _ctx(
    *,
    plugins: list[_FakePlugin],
    config: dict[str, Any],
    project: SimpleNamespace | None = None,
    knowledge_base: _FakeKnowledgeBase | None = None,
    events: _FakeEventPublisher | None = None,
) -> tuple[AgentContext, _FakeKnowledgeBase, _FakeEventPublisher]:
    kb = knowledge_base or _FakeKnowledgeBase()
    ev = events or _FakeEventPublisher()
    # Test doubles standing in for AgentContext's concrete (non-Protocol) collaborator
    # types — see agents/_shared/base.py's dependency-discipline note on why this package
    # never imports the concrete PluginRegistry/KnowledgeBaseClient/EventPublisher classes
    # it's typed against. mypy can't verify structural compatibility for a concrete class
    # the way it can for a Protocol; the runtime behavior is what these tests actually verify.
    ctx = AgentContext(
        project=project or _project(),  # type: ignore[arg-type]
        config=config,
        plugins=_FakeRegistry(plugins),  # type: ignore[arg-type]
        llm=None,  # type: ignore[arg-type]  # conversation_finder never calls ctx.llm
        knowledge_base=kb,  # type: ignore[arg-type]
        content=None,  # type: ignore[arg-type]  # conversation_finder never calls ctx.content
        events=ev,  # type: ignore[arg-type]
        logger=structlog.get_logger(),
        agent_run_id=uuid.uuid4(),
    )
    return ctx, kb, ev


def _result(
    url: str,
    *,
    title: str = "",
    body: str = "",
    platform_metadata: dict[str, Any] | None = None,
) -> PluginResult:
    return PluginResult(
        url=url, title=title, body=body, author=None, platform_metadata=platform_metadata or {}
    )


def test_key_and_config_schema() -> None:
    assert AGENT.key == "conversation_finder"
    from agents.conversation_finder.config import ConversationFinderConfig

    assert AGENT.config_schema is ConversationFinderConfig


@pytest.mark.asyncio
async def test_no_keywords_anywhere_returns_an_error_and_does_nothing() -> None:
    ctx, kb, ev = _ctx(plugins=[], config={})
    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 0
    assert result.errors
    assert kb.saved_calls == []
    assert ev.published == []


@pytest.mark.asyncio
async def test_falls_back_to_icp_config_keywords_when_agent_config_is_empty() -> None:
    plugin = _FakePlugin(
        key="dummy", results=[_result("https://x.invalid/1", title="crawl budget")]
    )
    ctx, kb, _ = _ctx(
        plugins=[plugin], config={}, project=_project(icp_keywords=["crawl budget"])
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.errors == []
    assert result.knowledge_items_created == 1
    assert plugin.calls[0].terms == ["crawl budget"]


@pytest.mark.asyncio
async def test_agent_config_keywords_take_priority_over_icp_config() -> None:
    plugin = _FakePlugin(key="dummy", results=[])
    ctx, _, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["canonical tags"]},
        project=_project(icp_keywords=["crawl budget"]),
    )

    await ConversationFinderAgent().run(ctx)

    assert plugin.calls[0].terms == ["canonical tags"]


@pytest.mark.asyncio
async def test_saves_results_at_or_above_min_score_and_skips_below() -> None:
    plugin = _FakePlugin(
        key="dummy",
        results=[
            _result("https://x.invalid/high", title="crawl budget"),  # score 1.0
            _result("https://x.invalid/low", body="unrelated post"),  # score 0.0
        ],
    )
    ctx, kb, ev = _ctx(
        plugins=[plugin], config={"keywords": ["crawl budget"], "min_score_to_save": 0.5}
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    assert [c["url"] for c in kb.saved_calls] == ["https://x.invalid/high"]
    assert len(ev.published) == 1
    assert ev.published[0]["event_type"] == "knowledge_item.created"
    assert ev.published[0]["payload"]["url"] == "https://x.invalid/high"


@pytest.mark.asyncio
async def test_deduplicates_the_same_url_within_a_single_run() -> None:
    plugin = _FakePlugin(
        key="dummy",
        results=[
            _result("https://x.invalid/dupe", title="crawl budget"),
            _result("https://x.invalid/dupe", title="crawl budget"),
        ],
    )
    ctx, kb, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    assert len(kb.saved_calls) == 1


@pytest.mark.asyncio
async def test_does_not_publish_an_event_for_a_refreshed_existing_item() -> None:
    plugin = _FakePlugin(
        key="dummy", results=[_result("https://x.invalid/known", title="crawl budget")]
    )
    kb = _FakeKnowledgeBase(existing_urls={"https://x.invalid/known"})
    ctx, kb, ev = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]}, knowledge_base=kb)

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 0  # refreshed, not newly created
    assert len(kb.saved_calls) == 1  # still upserted (tags/confidence refreshed)
    assert ev.published == []  # no event for a re-discovery


@pytest.mark.asyncio
async def test_one_plugin_raising_does_not_fail_the_whole_run() -> None:
    broken = _FakePlugin(key="broken", raises=True)
    healthy = _FakePlugin(
        key="dummy", results=[_result("https://x.invalid/ok", title="crawl budget")]
    )
    ctx, kb, _ = _ctx(plugins=[broken, healthy], config={"keywords": ["crawl budget"]})

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    assert kb.saved_calls[0]["url"] == "https://x.invalid/ok"
    assert result.summary["platforms_searched"] == ["broken", "dummy"]
    # The failure is still recorded, not just logged — otherwise the only way to learn a
    # search silently failed (e.g. a real API billing/auth error) is reading worker container
    # logs directly, since the run still reports "succeeded" by design.
    assert len(result.errors) == 1
    assert "broken" in result.errors[0]


@pytest.mark.asyncio
async def test_summary_reports_platforms_and_counts() -> None:
    plugin = _FakePlugin(
        key="dummy",
        results=[
            _result("https://x.invalid/a", title="crawl budget"),
            _result("https://x.invalid/b", title="crawl budget"),
        ],
    )
    ctx, _, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    result = await ConversationFinderAgent().run(ctx)

    assert result.summary["platforms_searched"] == ["dummy"]
    assert result.summary["results_found"] == 2
    assert result.summary["unique_urls"] == 2


@pytest.mark.asyncio
async def test_passes_title_body_excerpt_and_platform_metadata_through_verbatim() -> None:
    plugin = _FakePlugin(
        key="reddit",
        results=[
            _result(
                "https://x.invalid/1",
                title="Crawl budget question",
                body="Full post body about crawl budget.",
                platform_metadata={"subreddit": "SEO", "thing_id": "t3_abc123"},
            )
        ],
    )
    ctx, kb, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    await ConversationFinderAgent().run(ctx)

    saved = kb.saved_calls[0]
    assert saved["title"] == "Crawl budget question"
    assert saved["body_excerpt"] == "Full post body about crawl budget."
    assert saved["platform_metadata"] == {"subreddit": "SEO", "thing_id": "t3_abc123"}


@pytest.mark.asyncio
async def test_body_excerpt_is_capped() -> None:
    long_body = "x" * 5000
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget", body=long_body)]
    )
    ctx, kb, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    await ConversationFinderAgent().run(ctx)

    assert len(kb.saved_calls[0]["body_excerpt"]) == 2000
