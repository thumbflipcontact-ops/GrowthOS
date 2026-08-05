"""Integration tests for the real `run_agent_for_event` job body — see app/jobs/events.py
and docs/jobs/BACKGROUND_JOBS.md. Uses the real `content_agent` package and a real
`AnthropicProvider` wired to `httpx.MockTransport` (never a live network call — same
technique backend/tests/unit/test_llm_anthropic_provider.py uses) so this exercises the
actual wiring end to end: domain_events row -> AgentContext (with a real LLM round-trip
against a mocked transport) -> content_agent.run() -> content_items row -> agent_runs row.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import pytest
from arq.worker import Retry
from sqlalchemy import select

from app.core.config import Settings
from app.core.events import EventPublisher
from app.core.llm.anthropic_provider import AnthropicProvider
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.billing import Subscription, SubscriptionStatus
from app.models.content import ContentItem
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.services.knowledge_base import KnowledgeBaseClient

pytestmark = pytest.mark.integration


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x:x@localhost:5432/x",
        redis_url="redis://localhost:6379/0",
        anthropic_api_key="x",
        openai_api_key="x",
        secret_key="test-secret-key",
        credential_master_key="test-master-key",
    )


def _catalog() -> PluginCatalog:
    catalog = PluginCatalog()
    catalog.refresh(discover_installed_plugins())
    return catalog


def _anthropic_message_response(text: str) -> dict:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _draft_json(**overrides: object) -> str:
    payload = {
        "reply": "Here's a suggestion based on your crawl budget issue.",
        "confidence": 0.75,
        "reasoning": "The post clearly describes a crawl budget problem.",
        "evidence": ["Google isn't indexing all our pages."],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _llm_provider_returning(response_text: str, *, status_code: int = 200) -> AnthropicProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "boom"})
        return httpx.Response(200, json=_anthropic_message_response(response_text))

    return AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-4-5",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-evt-{suffix}")
    )
    # run_agent_for_event gates on an active subscription/trial (app/core/entitlements.py) —
    # this test suite exercises the job's own mechanics, not billing, so every project it
    # builds is entitled by default; see test_billing_entitlements.py for the gate itself.
    db_session.add(
        Subscription(
            org_id=org.id,
            polar_customer_id=f"cus_{suffix}",
            polar_subscription_id=f"sub_{suffix}",
            polar_product_id="prod_test",
            status=SubscriptionStatus.TRIALING,
        )
    )
    await db_session.flush()
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-evt-{suffix}")
    )


async def _make_knowledge_item_and_event(
    db_session, project: Project, *, confidence: str = "0.80"
):
    kb = KnowledgeBaseClient(db_session)
    item, _ = await kb.upsert_discovery(
        project_id=project.id,
        platform="reddit",
        url=f"https://reddit.com/r/SEO/{uuid.uuid4().hex[:8]}",
        tags=["crawl budget"],
        confidence=Decimal(confidence),
        title="Crawl budget question",
        body_excerpt="Google isn't indexing all our pages.",
        platform_metadata={"subreddit": "SEO", "thing_id": "t3_abc123"},
    )
    event = await EventPublisher(db_session).publish(
        project_id=project.id,
        event_type="knowledge_item.created",
        payload={
            "knowledge_item_id": str(item.id),
            "platform": item.platform,
            "url": item.url,
            "buying_intent": "none",
            "confidence": float(item.confidence),
            "tags": item.tags,
        },
    )
    return item, event


def _ctx(session_factory_for, *, llm_provider: AnthropicProvider) -> dict:
    return {
        "session_factory": session_factory_for,
        "settings": _settings(),
        "plugin_catalog": _catalog(),
        "llm_provider": llm_provider,
    }


@pytest.mark.asyncio
async def test_run_agent_for_event_drafts_and_persists_a_content_item(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    item, event = await _make_knowledge_item_and_event(db_session, project)

    llm = _llm_provider_returning(_draft_json())
    await run_agent_for_event(_ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id))

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.project_id == project.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.SUCCEEDED
    assert runs[0].summary["content_items_created"] == 1

    drafts = (
        await db_session.execute(select(ContentItem).where(ContentItem.project_id == project.id))
    ).scalars().all()
    assert len(drafts) == 1
    draft = drafts[0]
    # Auto-advanced by the self-check (Phase 2C) — see
    # docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md. A short, banned-phrase-free
    # reply passes, matching ARCHITECTURE.md §8's "immediately auto-advanced ... once the
    # agent's own self-check passes."
    assert draft.status.value == "pending_review"
    assert draft.type == "reddit_reply"
    assert draft.body == "Here's a suggestion based on your crawl budget issue."
    assert draft.confidence == Decimal("0.75")
    assert draft.reasoning == "The post clearly describes a crawl budget problem."
    assert draft.evidence == ["Google isn't indexing all our pages."]
    assert draft.target_platform == "reddit"
    assert draft.target_ref == "t3_abc123"
    assert draft.knowledge_item_id == item.id
    assert draft.created_by_agent_run_id == runs[0].id

    configs = (
        await db_session.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == project.id, AgentConfig.agent_key == "content_agent"
            )
        )
    ).scalars().all()
    assert len(configs) == 1  # auto-provisioned, exactly once


@pytest.mark.asyncio
async def test_run_agent_for_event_is_a_noop_for_a_missing_event(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    llm = _llm_provider_returning(_draft_json())
    await run_agent_for_event(
        _ctx(session_factory_for, llm_provider=llm), "content_agent", str(uuid.uuid4())
    )
    # No exception, and nothing to assert on — this is the "race between dispatch and
    # execution" no-op path, mirroring run_scheduled_agent's missing-config test.


@pytest.mark.asyncio
async def test_run_agent_for_event_skips_when_the_agent_is_disabled_for_the_project(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project)
    await AgentConfigRepository(db_session).add(
        AgentConfig(project_id=project.id, agent_key="content_agent", enabled=False)
    )

    llm = _llm_provider_returning(_draft_json())
    await run_agent_for_event(_ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id))

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.project_id == project.id))
    ).scalars().all()
    assert runs == []


@pytest.mark.asyncio
async def test_run_agent_for_event_records_a_failed_run_when_the_llm_call_fails(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project)

    llm = _llm_provider_returning("", status_code=500)
    # Regression test for docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1: asserting the
    # specific arq.worker.Retry type (not just "some exception") is what proves Arq's retry
    # policy actually applies now — a plain re-raise always raised *something*, just never the
    # one type Arq listens for.
    with pytest.raises(Retry):
        await run_agent_for_event(
            _ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id)
        )

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.project_id == project.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.FAILED


@pytest.mark.asyncio
async def test_run_agent_for_event_records_success_with_no_draft_when_the_response_is_unparseable(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project)

    llm = _llm_provider_returning("not json at all")
    await run_agent_for_event(_ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id))

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.project_id == project.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.SUCCEEDED  # a soft failure, not a hard one
    assert runs[0].summary["content_items_created"] == 0
    assert runs[0].summary["errors"]

    drafts = (
        await db_session.execute(select(ContentItem).where(ContentItem.project_id == project.id))
    ).scalars().all()
    assert drafts == []


@pytest.mark.asyncio
async def test_run_agent_for_event_skips_a_low_confidence_item_without_calling_the_llm(
    db_session, session_factory_for
) -> None:
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project, confidence="0.10")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_anthropic_message_response(_draft_json()))

    llm = AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-4-5",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await run_agent_for_event(_ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id))

    assert calls == []  # below the default min_confidence_for_reply — never called the LLM


@pytest.mark.asyncio
async def test_run_agent_for_event_leaves_a_too_long_reply_in_draft(
    db_session, session_factory_for
) -> None:
    """End-to-end proof (not just the agent-level unit test) that a failing self-check
    really does leave the row in `draft` via the real ContentDraftClient.submit_for_review —
    see docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md."""
    from app.jobs.events import run_agent_for_event

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project)
    # Pre-create the content_agent config so run_agent_for_event's get_or_create finds this
    # one instead of auto-provisioning an empty-config default.
    await AgentConfigRepository(db_session).add(
        AgentConfig(
            project_id=project.id, agent_key="content_agent", config={"max_reply_length": 50}
        )
    )

    long_reply = "x" * 200
    llm = _llm_provider_returning(_draft_json(reply=long_reply))
    await run_agent_for_event(
        _ctx(session_factory_for, llm_provider=llm), "content_agent", str(event.id)
    )

    drafts = (
        await db_session.execute(select(ContentItem).where(ContentItem.project_id == project.id))
    ).scalars().all()
    assert len(drafts) == 1
    assert drafts[0].status.value == "draft"

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.project_id == project.id))
    ).scalars().all()
    # content_items_created counts the draft's creation, not self-check success — the
    # self-check only gates promotion to pending_review, not whether a row was written.
    assert runs[0].summary["content_items_created"] == 1
    assert runs[0].summary["details"]["self_check_passed"] is False


class _FakeRedisCapturingEnqueues:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> None:
        self.calls.append((name, args, kwargs))


@pytest.mark.asyncio
async def test_dispatch_domain_events_enqueues_with_a_deterministic_job_id(
    db_session, session_factory_for
) -> None:
    """Regression test for docs/reviews/PRODUCTION_READINESS_REVIEW.md R1: dispatch_pending's
    enqueue closure used to call enqueue_job with no `_job_id`, so a dispatcher crash-and-
    redispatch would enqueue a brand-new job for an event/subscriber pair that may already
    have been processed. A deterministic id (event.id + agent_key) makes a re-enqueue for the
    same pair a no-op while the original is still queued/running."""
    from app.core.subscriptions import SubscriptionRegistry, discover_agent_subscriptions
    from app.jobs.events import _event_job_id, dispatch_domain_events

    project = await _make_project(db_session)
    _, event = await _make_knowledge_item_and_event(db_session, project)

    registry = SubscriptionRegistry()
    registry.refresh(discover_agent_subscriptions())

    fake_redis = _FakeRedisCapturingEnqueues()
    ctx = {
        "session_factory": session_factory_for,
        "subscription_registry": registry,
        "redis": fake_redis,
    }

    await dispatch_domain_events(ctx)

    assert fake_redis.calls, "content_agent should have been enqueued for knowledge_item.created"
    name, args, kwargs = fake_redis.calls[0]
    assert name == "run_agent_for_event"
    assert args == ("content_agent", str(event.id))
    assert kwargs.get("_job_id") == _event_job_id(event.id, "content_agent")
