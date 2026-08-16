"""Integration tests for WebhookDispatcher — see app/core/webhooks/dispatcher.py."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.events import EventPublisher
from app.core.webhooks.dispatcher import _BACKOFF_SCHEDULE, _MAX_ATTEMPTS, WebhookDispatcher
from app.models.identity import Organization
from app.models.project import Project
from app.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository

pytestmark = pytest.mark.integration


async def _make_project(db_session) -> Project:
    suffix = uuid.uuid4().hex[:8]
    org = await OrganizationRepository(db_session).add(Organization(name="Acme", slug=f"acme-wh-{suffix}"))
    return await ProjectRepository(db_session).add(Project(org_id=org.id, name="P", slug=f"p-wh-{suffix}"))


async def _make_subscription(db_session, project_id: uuid.UUID, *, secret: str = "s3cr3t") -> WebhookSubscription:
    sub = WebhookSubscription(
        project_id=project_id,
        target_url="https://hooks.example.invalid/threadly",
        event_types=["conversation.discovered"],
        secret=secret,
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler):
    import app.core.webhooks.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_delivers_a_new_knowledge_item_created_event(db_session, monkeypatch) -> None:
    project = await _make_project(db_session)
    subscription = await _make_subscription(db_session, project.id)
    await EventPublisher(db_session).publish(
        project_id=project.id,
        event_type="knowledge_item.created",
        payload={"knowledge_item_id": "abc", "url": "https://x.com/1"},
    )
    await db_session.commit()

    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)

    dispatcher = WebhookDispatcher(db_session)
    attempted = await dispatcher.run()

    assert attempted == 1
    assert len(received) == 1
    assert received[0].headers["X-Threadly-Event"] == "conversation.discovered"
    assert "X-Threadly-Signature" in received[0].headers
    body = json.loads(received[0].content)
    assert body["event"] == "conversation.discovered"
    assert body["data"]["url"] == "https://x.com/1"

    result = await db_session.execute(
        select(WebhookDelivery).where(WebhookDelivery.webhook_subscription_id == subscription.id)
    )
    delivery = result.scalar_one()
    assert delivery.status == WebhookDeliveryStatus.SUCCESS
    assert delivery.last_response_status == 200
    assert delivery.delivered_at is not None


@pytest.mark.asyncio
async def test_running_twice_never_creates_a_duplicate_delivery(db_session, monkeypatch) -> None:
    project = await _make_project(db_session)
    await _make_subscription(db_session, project.id)
    await EventPublisher(db_session).publish(
        project_id=project.id, event_type="knowledge_item.created", payload={}
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)

    dispatcher = WebhookDispatcher(db_session)
    await dispatcher.run()
    await dispatcher.run()  # a second cycle must not re-deliver the same event

    result = await db_session.execute(select(WebhookDelivery))
    deliveries = result.scalars().all()
    assert len(deliveries) == 1


@pytest.mark.asyncio
async def test_ignores_subscriptions_for_event_types_this_deployment_does_not_know(
    db_session, monkeypatch
) -> None:
    project = await _make_project(db_session)
    sub = WebhookSubscription(
        project_id=project.id,
        target_url="https://hooks.example.invalid/x",
        event_types=["some.future.event"],
        secret="s",
    )
    db_session.add(sub)
    await EventPublisher(db_session).publish(
        project_id=project.id, event_type="knowledge_item.created", payload={}
    )
    await db_session.commit()

    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    _patch_transport(monkeypatch, handler)

    dispatcher = WebhookDispatcher(db_session)
    attempted = await dispatcher.run()

    assert attempted == 0
    assert called is False


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_with_backoff(db_session, monkeypatch) -> None:
    project = await _make_project(db_session)
    await _make_subscription(db_session, project.id)
    await EventPublisher(db_session).publish(
        project_id=project.id, event_type="knowledge_item.created", payload={}
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _patch_transport(monkeypatch, handler)

    before = datetime.now(UTC)
    dispatcher = WebhookDispatcher(db_session)
    await dispatcher.run(now=before)

    result = await db_session.execute(select(WebhookDelivery))
    delivery = result.scalar_one()
    assert delivery.status == WebhookDeliveryStatus.PENDING
    assert delivery.attempt_count == 1
    assert delivery.next_attempt_at >= before + _BACKOFF_SCHEDULE[0]
    assert delivery.last_error is not None


@pytest.mark.asyncio
async def test_delivery_becomes_terminally_failed_after_max_attempts(db_session, monkeypatch) -> None:
    project = await _make_project(db_session)
    await _make_subscription(db_session, project.id)
    await EventPublisher(db_session).publish(
        project_id=project.id, event_type="knowledge_item.created", payload={}
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _patch_transport(monkeypatch, handler)

    now = datetime.now(UTC)
    dispatcher = WebhookDispatcher(db_session)
    for _attempt in range(_MAX_ATTEMPTS):
        await dispatcher.run(now=now)
        result = await db_session.execute(select(WebhookDelivery))
        delivery = result.scalar_one()
        now = delivery.next_attempt_at if delivery.next_attempt_at else now + timedelta(hours=7)

    result = await db_session.execute(select(WebhookDelivery))
    delivery = result.scalar_one()
    assert delivery.attempt_count == _MAX_ATTEMPTS
    assert delivery.status == WebhookDeliveryStatus.FAILED
