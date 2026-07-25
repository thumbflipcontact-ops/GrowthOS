"""End-to-end: EventPublisher (transactional outbox) → SubscriptionRegistry (filter
matching) → EventDispatcher (dispatch + mark). See ARCHITECTURE.md §7.
"""

from __future__ import annotations

import pytest
from agents._shared.subscriptions import AgentSubscriptions, EventSubscription

from app.core.dispatcher import EventDispatcher
from app.core.events import EventPublisher
from app.core.subscriptions import SubscriptionRegistry
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.event_repository import DomainEventRepository

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    org = Organization(name="Acme", slug="acme-events")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name="P", slug="p-events")
    db_session.add(project)
    await db_session.flush()
    return project


@pytest.mark.asyncio
async def test_publish_writes_an_undispatched_event(db_session) -> None:
    project = await _make_project(db_session)
    publisher = EventPublisher(db_session)

    event = await publisher.publish(
        project_id=project.id, event_type="knowledge_item.created", payload={"buying_intent": "high"}
    )
    assert event.dispatched_at is None

    pending = await DomainEventRepository(db_session).list_undispatched()
    assert event.id in {e.id for e in pending}


@pytest.mark.asyncio
async def test_dispatcher_enqueues_only_matching_subscribers_and_marks_dispatched(db_session) -> None:
    project = await _make_project(db_session)
    publisher = EventPublisher(db_session)
    await publisher.publish(
        project_id=project.id, event_type="knowledge_item.created", payload={"buying_intent": "high"}
    )
    await publisher.publish(
        project_id=project.id, event_type="knowledge_item.created", payload={"buying_intent": "low"}
    )
    await publisher.publish(project_id=project.id, event_type="content_item.published", payload={})

    registry = SubscriptionRegistry()
    registry.refresh(
        [
            AgentSubscriptions(
                "content_agent",
                (
                    EventSubscription(
                        "knowledge_item.created",
                        filter=lambda p: p.get("buying_intent") in ("medium", "high"),
                    ),
                ),
            ),
            AgentSubscriptions(
                "knowledge_base_agent", (EventSubscription("content_item.published"),)
            ),
        ]
    )

    enqueued: list[tuple[str, str]] = []

    async def enqueue(agent_key: str, event) -> None:
        enqueued.append((agent_key, event.event_type))

    dispatcher = EventDispatcher(db_session, registry)
    processed = await dispatcher.dispatch_pending(enqueue)

    assert processed == 3
    assert ("content_agent", "knowledge_item.created") in enqueued
    assert len(enqueued) == 2  # the low-intent knowledge_item never matches; content_item.published does
    assert ("knowledge_base_agent", "content_item.published") in enqueued

    remaining = await DomainEventRepository(db_session).list_undispatched()
    assert remaining == []


@pytest.mark.asyncio
async def test_dispatcher_is_a_no_op_with_no_pending_events(db_session) -> None:
    registry = SubscriptionRegistry()
    registry.refresh([])
    dispatcher = EventDispatcher(db_session, registry)

    calls = []

    async def enqueue(agent_key: str, event) -> None:
        calls.append(agent_key)

    processed = await dispatcher.dispatch_pending(enqueue)
    assert processed == 0
    assert calls == []


@pytest.mark.asyncio
async def test_event_with_no_subscribers_is_still_marked_dispatched(db_session) -> None:
    project = await _make_project(db_session)
    publisher = EventPublisher(db_session)
    await publisher.publish(project_id=project.id, event_type="nothing.listens.to.this", payload={})

    registry = SubscriptionRegistry()
    registry.refresh([])
    dispatcher = EventDispatcher(db_session, registry)

    async def enqueue(agent_key: str, event) -> None:
        raise AssertionError("should never be called")

    processed = await dispatcher.dispatch_pending(enqueue)
    assert processed == 1
    assert await DomainEventRepository(db_session).list_undispatched() == []
