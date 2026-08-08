"""End-to-end tests for ContentAgent.run() against a mocked knowledge base, content-draft
client, and LLM provider — see docs/agents/AGENT_ARCHITECTURE.md §Testing.
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
from agents.content_agent.agent import AGENT, ContentAgent
from app.core.llm.base import CompletionRequest, CompletionResult
from app.models.content import ContentItemStatus
from app.services.content_self_check import SelfCheckResult, run_self_check


def _knowledge_item(
    *,
    platform: str = "reddit",
    confidence: str = "0.80",
    title: str | None = "Crawl budget question",
    body_excerpt: str | None = "Google isn't indexing all our pages.",
    tags: list[str] | None = None,
    platform_metadata: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        platform=platform,
        confidence=Decimal(confidence),
        title=title,
        body_excerpt=body_excerpt,
        tags=tags or ["crawl budget"],
        platform_metadata=platform_metadata
        if platform_metadata is not None
        else {"subreddit": "SEO", "thing_id": "t3_abc123"},
    )


@dataclass
class _FakeKnowledgeBase:
    item: SimpleNamespace | None

    async def get(self, item_id: uuid.UUID) -> SimpleNamespace | None:
        return self.item


@dataclass
class _FakeContentDraftClient:
    created: list[dict[str, Any]] = field(default_factory=list)
    submitted: list[dict[str, Any]] = field(default_factory=list)

    async def create_draft(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), status=ContentItemStatus.DRAFT, **kwargs)

    async def submit_for_review(
        self,
        item: SimpleNamespace,
        *,
        org_id: uuid.UUID,
        max_length: int,
        banned_phrases: tuple[str, ...] = (),
    ) -> SelfCheckResult:
        check = run_self_check(item.body, max_length=max_length, banned_phrases=banned_phrases)
        if check.passed:
            item.status = ContentItemStatus.PENDING_REVIEW
        self.submitted.append({"item_id": item.id, "org_id": org_id, "passed": check.passed})
        return check


@dataclass
class _FakeLLMProvider:
    response_text: str = ""
    raises: Exception | None = None
    calls: list[CompletionRequest] = field(default_factory=list)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls.append(request)
        if self.raises is not None:
            raise self.raises
        return CompletionResult(text=self.response_text, model="test-model")


def _draft_json(
    *,
    reply: str = "Here's a suggestion.",
    confidence: float = 0.75,
    evidence: list[str] | None = None,
) -> str:
    import json

    default_evidence = ["Google isn't indexing all our pages."]
    return json.dumps(
        {
            "reply": reply,
            "confidence": confidence,
            "reasoning": "The post is clearly about crawl budget.",
            "evidence": evidence if evidence is not None else default_evidence,
        }
    )


def _project() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), org_id=uuid.uuid4(), brand_voice={})


def _ctx(
    *,
    item: SimpleNamespace | None,
    llm_response_text: str = "",
    llm_raises: Exception | None = None,
    config: dict[str, Any] | None = None,
    trigger_payload: dict[str, Any] | None = None,
) -> tuple[AgentContext, _FakeContentDraftClient, _FakeLLMProvider]:
    content = _FakeContentDraftClient()
    llm = _FakeLLMProvider(response_text=llm_response_text, raises=llm_raises)
    default_payload = {"knowledge_item_id": str(item.id)} if item is not None else {}
    ctx = AgentContext(
        project=_project(),  # type: ignore[arg-type]
        config=config or {},
        plugins=None,  # type: ignore[arg-type]  # content_agent never calls ctx.plugins
        llm=llm,  # structurally satisfies the LLMProvider Protocol — no ignore needed
        knowledge_base=_FakeKnowledgeBase(item=item),  # type: ignore[arg-type]
        content=content,  # type: ignore[arg-type]
        events=None,  # type: ignore[arg-type]  # content_agent never calls ctx.events
        logger=structlog.get_logger(),
        agent_run_id=uuid.uuid4(),
        trigger_payload=trigger_payload if trigger_payload is not None else default_payload,
    )
    return ctx, content, llm


def test_key_and_config_schema() -> None:
    assert AGENT.key == "content_agent"
    from agents.content_agent.config import ContentAgentConfig

    assert AGENT.config_schema is ContentAgentConfig


@pytest.mark.asyncio
async def test_no_trigger_payload_returns_an_error_and_drafts_nothing() -> None:
    ctx, content, llm = _ctx(item=None, trigger_payload={})

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert content.created == []
    assert llm.calls == []


@pytest.mark.asyncio
async def test_unknown_knowledge_item_returns_an_error() -> None:
    ctx, content, _ = _ctx(item=None, trigger_payload={"knowledge_item_id": str(uuid.uuid4())})

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert content.created == []


@pytest.mark.asyncio
async def test_unsupported_platform_is_skipped() -> None:
    item = _knowledge_item(platform="linkedin")
    ctx, content, llm = _ctx(item=item)

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert content.created == []
    assert llm.calls == []  # never even calls the LLM for an unsupported platform


@pytest.mark.asyncio
async def test_below_min_confidence_is_skipped() -> None:
    item = _knowledge_item(confidence="0.10")
    ctx, content, llm = _ctx(item=item, config={"min_confidence_for_reply": 0.5})

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert llm.calls == []


@pytest.mark.asyncio
async def test_no_grounding_text_is_skipped() -> None:
    item = _knowledge_item(title=None, body_excerpt=None)
    ctx, content, llm = _ctx(item=item)

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert llm.calls == []


@pytest.mark.asyncio
async def test_creates_a_draft_from_a_successful_completion() -> None:
    item = _knowledge_item()
    ctx, content, llm = _ctx(item=item, llm_response_text=_draft_json())

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 1
    assert len(content.created) == 1
    draft = content.created[0]
    assert draft["type"] == "reddit_reply"
    assert draft["body"] == "Here's a suggestion."
    assert draft["confidence"] == Decimal("0.75")
    assert draft["reasoning"] == "The post is clearly about crawl budget."
    assert draft["evidence"] == ["Google isn't indexing all our pages."]
    assert draft["target_platform"] == "reddit"
    assert draft["target_ref"] == "t3_abc123"
    assert draft["knowledge_item_id"] == item.id
    assert draft["source_agent_run_id"] == ctx.agent_run_id
    assert result.summary["self_check_passed"] is True
    assert result.summary["content_item_status"] == "pending_review"
    assert len(content.submitted) == 1
    assert content.submitted[0]["passed"] is True
    assert content.submitted[0]["org_id"] == ctx.project.org_id


@pytest.mark.asyncio
async def test_sends_system_and_user_messages_to_the_llm() -> None:
    item = _knowledge_item()
    ctx, _, llm = _ctx(item=item, llm_response_text=_draft_json())

    await ContentAgent().run(ctx)

    assert len(llm.calls) == 1
    roles = [m.role for m in llm.calls[0].messages]
    assert roles == ["system", "user"]
    assert "Crawl budget question" in llm.calls[0].messages[1].content


@pytest.mark.asyncio
async def test_missing_thing_id_yields_a_null_target_ref() -> None:
    item = _knowledge_item(platform_metadata={"subreddit": "SEO"})
    ctx, content, _ = _ctx(item=item, llm_response_text=_draft_json())

    await ContentAgent().run(ctx)

    assert content.created[0]["target_ref"] is None


@pytest.mark.asyncio
async def test_creates_a_tweet_draft_from_a_successful_completion() -> None:
    item = _knowledge_item(
        platform="twitter",
        title=None,  # tweets never have a title — see plugins/twitter/plugin.py
        body_excerpt="Anyone else struggling with crawl budget on a huge site?",
        platform_metadata={"tweet_id": "182736450192834765", "author_id": "999"},
    )
    ctx, content, llm = _ctx(item=item, llm_response_text=_draft_json())

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 1
    draft = content.created[0]
    assert draft["type"] == "tweet"
    assert draft["target_platform"] == "twitter"
    assert draft["target_ref"] == "182736450192834765"
    # Not a Reddit reply — build_user_prompt must not have been asked for a subreddit.
    assert len(llm.calls) == 1
    assert "crawl budget on a huge site" in llm.calls[0].messages[1].content


@pytest.mark.asyncio
async def test_tweet_missing_tweet_id_yields_a_null_target_ref() -> None:
    item = _knowledge_item(platform="twitter", platform_metadata={"author_id": "999"})
    ctx, content, _ = _ctx(item=item, llm_response_text=_draft_json())

    await ContentAgent().run(ctx)

    assert content.created[0]["target_ref"] is None


@pytest.mark.asyncio
async def test_a_tweet_reply_exceeding_max_tweet_length_fails_the_self_check() -> None:
    item = _knowledge_item(
        platform="twitter", platform_metadata={"tweet_id": "1", "author_id": "2"}
    )
    long_reply = "x" * 300  # over X's 280-character limit
    ctx, content, _ = _ctx(item=item, llm_response_text=_draft_json(reply=long_reply))

    result = await ContentAgent().run(ctx)

    # Same "still created, just stays in draft" behavior as Reddit's equivalent test —
    # the self-check gates promotion, not creation.
    assert result.content_items_created == 1
    assert result.summary["self_check_passed"] is False
    assert any("max_length" in reason for reason in result.summary["self_check_reasons"])
    assert content.submitted[0]["passed"] is False


@pytest.mark.asyncio
async def test_unparseable_llm_response_records_an_error_and_creates_no_draft() -> None:
    item = _knowledge_item()
    ctx, content, llm = _ctx(item=item, llm_response_text="not json at all")

    result = await ContentAgent().run(ctx)

    assert result.content_items_created == 0
    assert result.errors
    assert content.created == []
    assert len(llm.calls) == 1  # the LLM *was* called — only parsing failed


@pytest.mark.asyncio
async def test_result_summary_reports_the_triggering_item_and_draft() -> None:
    item = _knowledge_item()
    ctx, _, _ = _ctx(item=item, llm_response_text=_draft_json())

    result = await ContentAgent().run(ctx)

    assert result.summary["knowledge_item_id"] == str(item.id)
    assert result.summary["platform"] == "reddit"
    assert "content_item_id" in result.summary
    assert result.summary["draft_confidence"] == 0.75


@pytest.mark.asyncio
async def test_a_reply_exceeding_max_reply_length_fails_the_self_check_and_stays_in_draft() -> None:
    item = _knowledge_item()
    long_reply = "x" * 200
    ctx, content, _ = _ctx(
        item=item,
        llm_response_text=_draft_json(reply=long_reply),
        config={"max_reply_length": 50},
    )

    result = await ContentAgent().run(ctx)

    # The draft is still created and counted — the self-check only gates promotion, not
    # creation — but it stays in draft, and content_item_status/self_check reflect that.
    assert result.content_items_created == 1
    assert result.summary["self_check_passed"] is False
    assert result.summary["content_item_status"] == "draft"
    assert any("max_length" in reason for reason in result.summary["self_check_reasons"])
    assert content.submitted[0]["passed"] is False


@pytest.mark.asyncio
async def test_a_reply_containing_a_banned_phrase_fails_the_self_check() -> None:
    item = _knowledge_item()
    ctx, content, _ = _ctx(
        item=item,
        llm_response_text=_draft_json(reply="Buy our product now, guaranteed results!"),
        config={"banned_phrases": ["guaranteed results"]},
    )

    result = await ContentAgent().run(ctx)

    assert result.summary["self_check_passed"] is False
    assert result.summary["content_item_status"] == "draft"
    assert any("banned phrase" in reason for reason in result.summary["self_check_reasons"])
