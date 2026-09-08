"""End-to-end tests for ConversationFinderAgent.run() against a mocked plugin registry,
knowledge base, event publisher, and LLM provider — see docs/agents/AGENT_ARCHITECTURE.md
§Testing ("every agent's test suite runs against a mocked PluginRegistry ... and a
mocked/recorded LLMProvider response"). `_ctx()`'s default `_FakeLLM` auto-echoes a
plausible LeadScoreBatch for whatever candidates were actually sent to it, so every test that
doesn't care about LLM scoring specifically (most of the ones below, predating the LLM
scoring pass) keeps behaving exactly as it did before that pass existed — see
_score_candidates_with_llm-specific tests further down for the LLM-scoring contract itself.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from plugins._shared.base import PluginQuery, PluginResult

from agents._shared.base import AgentContext
from agents.conversation_finder.agent import AGENT, ConversationFinderAgent
from agents.conversation_finder.prompts import LeadScore, LeadScoreBatch


@dataclass
class _FakePlugin:
    key: str
    results: list[PluginResult] = field(default_factory=list)
    raises: bool = False
    raise_exc: Exception | None = None
    calls: list[PluginQuery] = field(default_factory=list)

    @property
    def manifest(self) -> SimpleNamespace:
        return SimpleNamespace(key=self.key)

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        self.calls.append(query)
        if self.raise_exc is not None:
            raise self.raise_exc
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
        buying_intent: str | None = None,
        pain_point: str | None = None,
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
                "buying_intent": buying_intent,
                "pain_point": pain_point,
            }
        )
        item = SimpleNamespace(
            id=uuid.uuid4(),
            project_id=project_id,
            platform=platform,
            url=url,
            tags=tags,
            confidence=confidence,
            buying_intent=SimpleNamespace(value=buying_intent or "none"),
        )
        return item, created


_PROMPT_URL_RE = re.compile(r"url: (\S+)")


def _auto_lead_score_response(request: Any) -> str:
    """Default `_FakeLLM` behavior: echo back a plausible high-relevance LeadScore for every
    candidate actually present in the batched prompt, so tests that don't care about LLM
    scoring specifically don't need to hand-construct a response for it."""
    user_message = next(m for m in request.messages if m.role == "user")
    urls = _PROMPT_URL_RE.findall(user_message.content)
    batch = LeadScoreBatch(
        scores=[
            LeadScore(url=url, relevance=1.0, buying_intent="high", reasoning="Looks relevant.")
            for url in urls
        ]
    )
    return batch.model_dump_json()


@dataclass
class _FakeLLM:
    response_text: str | None = None
    raises: bool = False
    calls: list[Any] = field(default_factory=list)

    async def complete(self, request: Any) -> SimpleNamespace:
        self.calls.append(request)
        if self.raises:
            raise RuntimeError("llm blew up")
        text = self.response_text if self.response_text is not None else _auto_lead_score_response(
            request
        )
        # model/input_tokens/output_tokens mirror the real CompletionResult shape (see
        # app/core/llm/base.py) — ctx.usage.record() reads these, see _FakeUsage below.
        return SimpleNamespace(text=text, model="fake-model", input_tokens=100, output_tokens=50)


@dataclass
class _FakeEventPublisher:
    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(
        self, *, project_id: uuid.UUID, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.published.append(
            {"project_id": project_id, "event_type": event_type, "payload": payload}
        )


@dataclass
class _FakeUsage:
    """Stands in for LlmUsageClient (app/services/llm_usage.py) — records each call's
    kwargs rather than computing a real cost, since these tests care that a call happened
    with the right attribution, not the dollar figure pricing.py produces."""

    recorded: list[dict[str, Any]] = field(default_factory=list)

    async def record(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


def _project(icp_keywords: list[str] | None = None) -> SimpleNamespace:
    icp_config = {"keywords": icp_keywords} if icp_keywords is not None else {}
    return SimpleNamespace(
        id=uuid.uuid4(), org_id=uuid.uuid4(), icp_config=icp_config, name="Acme", brand_voice={}
    )


def _ctx(
    *,
    plugins: list[_FakePlugin],
    config: dict[str, Any],
    project: SimpleNamespace | None = None,
    knowledge_base: _FakeKnowledgeBase | None = None,
    events: _FakeEventPublisher | None = None,
    llm: _FakeLLM | None = None,
    usage: _FakeUsage | None = None,
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
        llm=llm or _FakeLLM(),  # type: ignore[arg-type]
        knowledge_base=kb,  # type: ignore[arg-type]
        content=None,  # type: ignore[arg-type]  # conversation_finder never calls ctx.content
        events=ev,  # type: ignore[arg-type]
        usage=usage or _FakeUsage(),  # type: ignore[arg-type]
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
    assert result.operator_alerts == []


class _PluginBillingError(Exception):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.asyncio
async def test_plugin_billing_error_gets_generic_customer_message_and_operator_alert() -> None:
    """A plugin's own API client running out of prepaid credits (HTTP 402) is the platform's
    problem, not this customer's — their own Agent settings page must not show them a raw
    detail that reads as "your connection is broken" when it isn't, or that they have no way
    to act on. The specific detail instead goes to operator_alerts, which the job runner
    (app/jobs/agent_runs.py) forwards to error tracking."""
    broken = _FakePlugin(
        key="twitter",
        raise_exc=_PluginBillingError("X returned 402: credits depleted", status_code=402),
    )
    ctx, _, _ = _ctx(plugins=[broken], config={"keywords": ["seo"]})

    result = await ConversationFinderAgent().run(ctx)

    assert len(result.errors) == 1
    assert "credits depleted" not in result.errors[0]
    assert "twitter" in result.errors[0]

    assert len(result.operator_alerts) == 1
    assert "credits depleted" in result.operator_alerts[0]
    assert "402" in result.operator_alerts[0]


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

    assert result.summary["terms"] == ["crawl budget"]
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
async def test_llm_score_and_reasoning_are_saved_as_confidence_and_pain_point() -> None:
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget")]
    )
    response = LeadScoreBatch(
        scores=[
            LeadScore(
                url="https://x.invalid/1",
                relevance=0.9,
                buying_intent="high",
                reasoning="Actively asking for a crawl budget tool.",
            )
        ]
    ).model_dump_json()
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"]},
        llm=_FakeLLM(response_text=response),
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    saved = kb.saved_calls[0]
    assert saved["confidence"] == Decimal("0.9")
    assert saved["buying_intent"] == "high"
    assert saved["pain_point"] == "Actively asking for a crawl budget tool."


@pytest.mark.asyncio
async def test_records_llm_usage_for_the_scoring_call() -> None:
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget")]
    )
    ctx, _, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    await ConversationFinderAgent().run(ctx)

    assert len(ctx.usage.recorded) == 1  # type: ignore[attr-defined]
    call = ctx.usage.recorded[0]  # type: ignore[attr-defined]
    assert call["org_id"] == ctx.project.org_id
    assert call["project_id"] == ctx.project.id
    assert call["purpose"] == "conversation_finder.lead_scoring"
    assert call["agent_run_id"] == ctx.agent_run_id


@pytest.mark.asyncio
async def test_no_llm_usage_recorded_when_there_are_no_candidates() -> None:
    plugin = _FakePlugin(key="reddit", results=[])
    ctx, _, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    await ConversationFinderAgent().run(ctx)

    assert ctx.usage.recorded == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_llm_scores_are_matched_back_to_candidates_by_url_not_order() -> None:
    plugin = _FakePlugin(
        key="reddit",
        results=[
            _result("https://x.invalid/a", title="crawl budget"),
            _result("https://x.invalid/b", title="crawl budget"),
        ],
    )
    # Response lists "b" before "a" and uses different scores — matching must go by url, not
    # by the order candidates were sent in.
    response = LeadScoreBatch(
        scores=[
            LeadScore(url="https://x.invalid/b", relevance=0.3, buying_intent="low", reasoning="b"),
            LeadScore(url="https://x.invalid/a", relevance=0.8, buying_intent="high", reasoning="a"),
        ]
    ).model_dump_json()
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"]},
        llm=_FakeLLM(response_text=response),
    )

    await ConversationFinderAgent().run(ctx)

    by_url = {c["url"]: c for c in kb.saved_calls}
    assert by_url["https://x.invalid/a"]["confidence"] == Decimal("0.8")
    assert by_url["https://x.invalid/b"]["confidence"] == Decimal("0.3")


@pytest.mark.asyncio
async def test_candidate_missing_from_llm_response_falls_back_to_keyword_score() -> None:
    plugin = _FakePlugin(
        key="reddit",
        results=[
            _result("https://x.invalid/covered", title="crawl budget"),
            _result("https://x.invalid/missing", title="crawl budget"),
        ],
    )
    # Only one of the two candidates is echoed back by the model.
    response = LeadScoreBatch(
        scores=[
            LeadScore(
                url="https://x.invalid/covered",
                relevance=0.95,
                buying_intent="high",
                reasoning="covered",
            )
        ]
    ).model_dump_json()
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"]},
        llm=_FakeLLM(response_text=response),
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 2
    by_url = {c["url"]: c for c in kb.saved_calls}
    assert by_url["https://x.invalid/covered"]["confidence"] == Decimal("0.95")
    assert by_url["https://x.invalid/covered"]["buying_intent"] == "high"
    # Fell back to the deterministic keyword score — same value ranking.score_result() would
    # produce for a single-term title match — with no buying_intent/pain_point set.
    missing = by_url["https://x.invalid/missing"]
    assert missing["buying_intent"] is None
    assert missing["pain_point"] is None
    assert missing["confidence"] > 0


@pytest.mark.asyncio
async def test_llm_call_raising_falls_back_to_keyword_score_for_every_candidate() -> None:
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget")]
    )
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"]},
        llm=_FakeLLM(raises=True),
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    saved = kb.saved_calls[0]
    assert saved["buying_intent"] is None
    assert saved["pain_point"] is None
    assert saved["confidence"] > 0
    assert any("AI lead scoring" in e for e in result.errors)


@pytest.mark.asyncio
async def test_unparseable_llm_response_falls_back_to_keyword_score_for_every_candidate() -> None:
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget")]
    )
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"]},
        llm=_FakeLLM(response_text="not json at all"),
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 1
    saved = kb.saved_calls[0]
    assert saved["buying_intent"] is None
    assert saved["pain_point"] is None
    assert any("AI lead scoring" in e for e in result.errors)


@pytest.mark.asyncio
async def test_llm_relevance_gates_min_score_to_save_not_the_keyword_score() -> None:
    """A candidate that clears the cheap keyword pre-filter (score > 0) but that the LLM
    judges as not actually relevant should NOT be saved — min_score_to_save must gate on
    whichever score actually ends up on the item, not the pre-filter score."""
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget tool")]
    )
    response = LeadScoreBatch(
        scores=[
            LeadScore(
                url="https://x.invalid/1",
                relevance=0.05,
                buying_intent="none",
                reasoning="Uses the words but isn't actually about this.",
            )
        ]
    ).model_dump_json()
    ctx, kb, _ = _ctx(
        plugins=[plugin],
        config={"keywords": ["crawl budget"], "min_score_to_save": 0.2},
        llm=_FakeLLM(response_text=response),
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 0
    assert kb.saved_calls == []


@pytest.mark.asyncio
async def test_candidates_across_multiple_plugins_are_scored_in_one_batched_llm_call() -> None:
    plugin_a = _FakePlugin(key="reddit", results=[_result("https://x.invalid/a", title="crawl budget")])
    plugin_b = _FakePlugin(key="dummy", results=[_result("https://x.invalid/b", title="crawl budget")])
    llm = _FakeLLM()
    ctx, kb, _ = _ctx(
        plugins=[plugin_a, plugin_b], config={"keywords": ["crawl budget"]}, llm=llm
    )

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 2
    assert len(llm.calls) == 1  # one call scores both plugins' candidates together
    user_message = next(m for m in llm.calls[0].messages if m.role == "user")
    assert "https://x.invalid/a" in user_message.content
    assert "https://x.invalid/b" in user_message.content


@pytest.mark.asyncio
async def test_llm_is_not_called_when_there_are_no_candidates() -> None:
    plugin = _FakePlugin(key="reddit", results=[_result("https://x.invalid/1", body="unrelated")])
    llm = _FakeLLM()
    ctx, kb, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]}, llm=llm)

    result = await ConversationFinderAgent().run(ctx)

    assert result.knowledge_items_created == 0
    assert llm.calls == []
    assert kb.saved_calls == []


@pytest.mark.asyncio
async def test_body_excerpt_is_capped() -> None:
    long_body = "x" * 5000
    plugin = _FakePlugin(
        key="reddit", results=[_result("https://x.invalid/1", title="crawl budget", body=long_body)]
    )
    ctx, kb, _ = _ctx(plugins=[plugin], config={"keywords": ["crawl budget"]})

    await ConversationFinderAgent().run(ctx)

    assert len(kb.saved_calls[0]["body_excerpt"]) == 2000
