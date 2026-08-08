"""Integration tests for the real `run_scheduled_agent` job body — see
app/jobs/agent_runs.py and docs/jobs/BACKGROUND_JOBS.md. Uses the real `dummy` plugin
(Searchable, pip installed editable) and the real `conversation_finder` agent so this
exercises the actual wiring: agent_configs row -> PluginRegistry -> agent.run() ->
knowledge_items + domain_events -> agent_runs row, not a mocked stand-in for any of it.
"""

from __future__ import annotations

import uuid

import pytest
from arq.worker import Retry
from sqlalchemy import select

from app.core.config import Settings
from app.core.llm.factory import build_llm_provider
from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
from app.models.agent import AgentConfig, AgentRun, AgentRunStatus
from app.models.billing import Subscription, SubscriptionStatus
from app.models.event import DomainEvent
from app.models.identity import Organization
from app.models.knowledge import KnowledgeItem
from app.models.plugin import PluginCapability, PluginConnection
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

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


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-run-{suffix}")
    )
    # run_scheduled_agent gates on an active subscription/trial (app/core/entitlements.py) —
    # this test suite exercises agent-run mechanics, not billing, so every project it builds
    # is entitled by default; see test_billing_entitlements.py for the gate itself.
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
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-run-{suffix}")
    )


async def _connect_dummy_as_searchable(db_session, project: Project) -> None:
    db_session.add(
        PluginConnection(
            project_id=project.id,
            plugin_key="dummy",
            capabilities_enabled=[PluginCapability.SEARCHABLE],
        )
    )
    await db_session.flush()


async def _ctx(session_factory_for) -> dict:
    settings = _settings()
    return {
        "session_factory": session_factory_for,
        "settings": settings,
        "plugin_catalog": _catalog(),
        # conversation_finder never calls ctx.llm — constructing a real provider is safe
        # here (no network call happens until .complete() is invoked) and keeps this test's
        # fake ctx dict shaped exactly like the real worker's.
        "llm_provider": build_llm_provider(settings),
    }


@pytest.mark.asyncio
async def test_run_scheduled_agent_discovers_and_persists_a_knowledge_item(
    db_session, session_factory_for
) -> None:
    # Imported locally, after the DB fixtures above have already set DATABASE_URL in the
    # environment — app/jobs/agent_runs.py's WorkerSettings resolves get_settings() at
    # module-import time, which would otherwise fail before postgres_url's fixture runs.
    from app.jobs.agent_runs import run_scheduled_agent

    project = await _make_project(db_session)
    await _connect_dummy_as_searchable(db_session, project)
    config = await AgentConfigRepository(db_session).add(
        AgentConfig(
            project_id=project.id,
            agent_key="conversation_finder",
            config={"keywords": ["indexing"]},
            enabled=True,
        )
    )

    await run_scheduled_agent(await _ctx(session_factory_for), str(config.id))

    runs = (
        await db_session.execute(
            select(AgentRun).where(AgentRun.agent_config_id == config.id)
        )
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.SUCCEEDED
    assert runs[0].summary["knowledge_items_created"] == 1
    assert runs[0].started_at is not None
    assert runs[0].finished_at is not None

    items = (
        await db_session.execute(
            select(KnowledgeItem).where(KnowledgeItem.project_id == project.id)
        )
    ).scalars().all()
    assert len(items) == 1
    assert items[0].platform == "dummy"
    assert items[0].source_agent_run_id == runs[0].id
    assert items[0].title == "dummy result"
    assert items[0].body_excerpt is not None and "indexing" in items[0].body_excerpt
    assert items[0].platform_metadata == {}

    events = (
        await db_session.execute(
            select(DomainEvent).where(DomainEvent.event_type == "knowledge_item.created")
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].payload["url"] == items[0].url


@pytest.mark.asyncio
async def test_run_scheduled_agent_runs_a_disabled_config_when_invoked_directly(
    db_session, session_factory_for
) -> None:
    """This job body has no `enabled` gate of its own on purpose — see the comment above that
    check's removal site in app/jobs/agent_runs.py. The cron scheduler (app/core/scheduler.py)
    already only ever enqueues for configs it queried as enabled in the first place, so a
    disabled config's schedule genuinely never fires on its own; a gate *here* would only ever
    fire for the other caller of this same job, the on-demand trigger endpoint
    (app/api/v1/agent_configs.py) — where it would silently no-op an explicit "Run now" click
    for any project that had ever unchecked "Run automatically." This test simulates exactly
    that: invoking the job directly (as the trigger endpoint's enqueue would) against a
    disabled config, and asserting it still runs."""
    from app.jobs.agent_runs import run_scheduled_agent

    project = await _make_project(db_session)
    await _connect_dummy_as_searchable(db_session, project)
    config = await AgentConfigRepository(db_session).add(
        AgentConfig(
            project_id=project.id,
            agent_key="conversation_finder",
            config={"keywords": ["indexing"]},
            enabled=False,
        )
    )

    await run_scheduled_agent(await _ctx(session_factory_for), str(config.id))

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.agent_config_id == config.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_scheduled_agent_is_a_noop_for_a_missing_config(
    db_session, session_factory_for
) -> None:
    from app.jobs.agent_runs import run_scheduled_agent

    # Should log and return, not raise — a race where a config is deleted between enqueue
    # and job execution must not crash the worker.
    await run_scheduled_agent(await _ctx(session_factory_for), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_run_scheduled_agent_records_a_failed_run_and_reraises_when_the_agent_errors(
    db_session, session_factory_for, monkeypatch
) -> None:
    from app.jobs.agent_runs import run_scheduled_agent

    project = await _make_project(db_session)
    config = await AgentConfigRepository(db_session).add(
        AgentConfig(project_id=project.id, agent_key="conversation_finder", enabled=True)
    )

    import agents.conversation_finder.agent as agent_module

    async def _boom(self, ctx):
        raise RuntimeError("agent blew up")

    monkeypatch.setattr(agent_module.ConversationFinderAgent, "run", _boom)

    # Regression test for docs/reviews/PRODUCTION_READINESS_REVIEW.md §3.1: a plain re-raise
    # here never actually triggered Arq's retry policy, regardless of max_tries — Arq only
    # retries a job that raises its own arq.worker.Retry. Asserting the raised type (not just
    # "some exception") is what actually proves the fix, since the job always raised
    # *something*; the bug was in *what*.
    with pytest.raises(Retry):
        await run_scheduled_agent(await _ctx(session_factory_for), str(config.id))

    runs = (
        await db_session.execute(select(AgentRun).where(AgentRun.agent_config_id == config.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.FAILED
    assert runs[0].error == "agent blew up"
