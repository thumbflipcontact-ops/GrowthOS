"""See docs/jobs/BACKGROUND_JOBS.md "Scheduling implementation note"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.scheduler import Scheduler
from app.models.agent import AgentConfig
from app.models.identity import Organization
from app.models.project import Project

pytestmark = pytest.mark.integration


async def _make_agent_config(db_session, *, cron: str | None, enabled: bool = True) -> AgentConfig:
    org = Organization(name="Acme", slug="acme-sched-it")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug="p-sched-it")
    db_session.add(project)
    await db_session.flush()
    config = AgentConfig(
        project_id=project.id, agent_key="conversation_finder", schedule_cron=cron, enabled=enabled
    )
    db_session.add(config)
    await db_session.flush()
    return config


def _recording_enqueue(sink: list):
    async def enqueue(config: AgentConfig) -> None:
        sink.append(config.id)

    return enqueue


async def _noop_enqueue(config: AgentConfig) -> None:
    pass


@pytest.mark.asyncio
async def test_first_tick_never_enqueues(db_session, session_factory_for) -> None:
    await _make_agent_config(db_session, cron="* * * * *")
    scheduler = Scheduler(session_factory_for)

    enqueued: list = []
    n = await scheduler.tick(now=datetime.now(UTC), enqueue=_recording_enqueue(enqueued))
    assert n == 0
    assert enqueued == []


@pytest.mark.asyncio
async def test_due_config_is_enqueued_on_second_tick(db_session, session_factory_for) -> None:
    config = await _make_agent_config(db_session, cron="* * * * *")
    scheduler = Scheduler(session_factory_for)

    now = datetime.now(UTC)
    await scheduler.tick(now=now, enqueue=_noop_enqueue)

    enqueued: list = []
    n = await scheduler.tick(now=now + timedelta(minutes=2), enqueue=_recording_enqueue(enqueued))
    assert n == 1
    assert enqueued == [config.id]


@pytest.mark.asyncio
async def test_disabled_config_is_never_enqueued(db_session, session_factory_for) -> None:
    await _make_agent_config(db_session, cron="* * * * *", enabled=False)
    scheduler = Scheduler(session_factory_for)

    now = datetime.now(UTC)
    await scheduler.tick(now=now, enqueue=_noop_enqueue)
    enqueued: list = []
    await scheduler.tick(now=now + timedelta(minutes=2), enqueue=_recording_enqueue(enqueued))
    assert enqueued == []


@pytest.mark.asyncio
async def test_config_with_no_schedule_is_never_polled(db_session, session_factory_for) -> None:
    """schedule_cron=None means on-demand only — see docs/database/SCHEMA.md."""
    await _make_agent_config(db_session, cron=None)
    scheduler = Scheduler(session_factory_for)

    now = datetime.now(UTC)
    await scheduler.tick(now=now, enqueue=_noop_enqueue)
    enqueued: list = []
    await scheduler.tick(now=now + timedelta(minutes=2), enqueue=_recording_enqueue(enqueued))
    assert enqueued == []
