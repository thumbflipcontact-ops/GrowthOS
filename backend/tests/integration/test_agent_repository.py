"""Integration tests for AgentConfigRepository.get_or_create — see
app/repositories/agent_repository.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.agent import AgentConfig
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(
        Organization(name="Acme", slug=f"acme-agentrepo-{suffix}")
    )
    return await ProjectRepository(db_session).add(
        Project(org_id=org.id, name="ScoutSEO", slug=f"scoutseo-agentrepo-{suffix}")
    )


@pytest.mark.asyncio
async def test_get_or_create_returns_the_existing_row_when_one_is_already_there(
    db_session,
) -> None:
    project = await _make_project(db_session)
    repo = AgentConfigRepository(db_session)
    first = await repo.get_or_create(project.id, "content_agent")
    second = await repo.get_or_create(project.id, "content_agent")
    assert second.id == first.id


@pytest.mark.asyncio
async def test_get_or_create_creates_exactly_one_row_for_a_brand_new_pair(db_session) -> None:
    project = await _make_project(db_session)
    config = await AgentConfigRepository(db_session).get_or_create(project.id, "content_agent")

    rows = (
        await db_session.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == project.id, AgentConfig.agent_key == "content_agent"
            )
        )
    ).scalars().all()
    assert [r.id for r in rows] == [config.id]


@pytest.mark.asyncio
async def test_get_or_create_recovers_when_a_concurrent_insert_wins_the_race(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for a real production incident: when a single conversation_finder run
    discovers several leads at once, app/jobs/events.py's dispatcher enqueues one
    run_agent_for_event job per lead, often within milliseconds of each other — the first
    time content_agent fires for a project, every one of those jobs calls this method for the
    *same* (project_id, agent_key). Two concurrent calls could both see "nothing exists yet"
    before either committed its own INSERT; the table's unique(project_id, agent_key)
    constraint then let exactly one succeed and the other crash with an uncaught
    IntegrityError — no AgentRun row, no visible error, the lead just silently never got a
    drafted reply. This reproduces that exact race in one session (Postgres enforces a unique
    constraint at flush time even within a single uncommitted transaction, so a second INSERT
    against an already-flushed key fails immediately, the same as a second session's INSERT
    landing after the first session's commit would)."""
    project = await _make_project(db_session)
    repo = AgentConfigRepository(db_session)
    real_get = repo.get_by_project_and_key
    calls = 0

    async def flaky_get(project_id: uuid.UUID, agent_key: str) -> AgentConfig | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            # The race window: a genuinely concurrent second call would see this too, before
            # either has committed.
            return None
        return await real_get(project_id, agent_key)

    monkeypatch.setattr(repo, "get_by_project_and_key", flaky_get)

    # The "other" concurrent call that wins the race and gets its row in first.
    winner = AgentConfig(project_id=project.id, agent_key="content_agent")
    db_session.add(winner)
    await db_session.flush()

    result = await repo.get_or_create(project.id, "content_agent")

    assert result.id == winner.id
    assert calls == 2  # the initial (fooled) check, then the post-conflict recovery check

    rows = (
        await db_session.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == project.id, AgentConfig.agent_key == "content_agent"
            )
        )
    ).scalars().all()
    assert [r.id for r in rows] == [winner.id]  # no duplicate left behind by the failed insert
