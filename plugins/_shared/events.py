"""A dependency-free view onto the core event-publishing mechanism, for `WebhookReceivable`
plugins. See docs/plugins/PLUGIN_ARCHITECTURE.md §"Webhooks and events" and
docs/decisions/0006-event-driven-agent-communication.md.

Why this module exists: `WebhookReceivable.handle_webhook()` is documented to write its
resulting row and that row's domain event in a single transaction — the same transactional
outbox guarantee every scheduled agent write gets. The real `EventPublisher` lives in
`app/core/events.py`, which `plugins/_shared` must never import (the plugin SDK stays free of
any `backend/app` dependency — see base.py's module docstring). `DomainEventPublisher` is the
narrow structural shape a plugin needs to call `.publish(...)`, without knowing anything about
SQLAlchemy sessions or the `DomainEvent` ORM model. `app.core.events.EventPublisher` already
satisfies this Protocol structurally — no inheritance or registration required — so the
registry can hand a real `EventPublisher` to any `WebhookReceivable` plugin as-is.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class DomainEventPublisher(Protocol):
    """`payload` is whatever JSON-serializable dict describes the event (mirrors
    `app.core.events.EventPublisher.publish`). The return value is deliberately untyped here
    (`object`, not `DomainEvent`) — a plugin has no legitimate reason to inspect it; the
    write already happened by the time `publish()` returns."""

    async def publish(
        self, *, project_id: uuid.UUID, event_type: str, payload: dict
    ) -> object: ...


__all__ = ["DomainEventPublisher"]
