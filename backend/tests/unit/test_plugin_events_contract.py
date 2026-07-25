"""See docs/plugins/PLUGIN_ARCHITECTURE.md §"Webhooks and events".

Proves the fix for the WebhookReceivable event-publishing gap found in the Platform
Readiness Review: `app.core.events.EventPublisher` (which plugins/_shared must never import)
structurally satisfies `plugins._shared.events.DomainEventPublisher` (which it may import),
so the registry can hand a real EventPublisher to any WebhookReceivable plugin.
"""

from __future__ import annotations

from plugins._shared.events import DomainEventPublisher

from app.core.events import EventPublisher


def test_event_publisher_satisfies_domain_event_publisher_protocol() -> None:
    publisher = EventPublisher(session=object())  # type: ignore[arg-type]
    assert isinstance(publisher, DomainEventPublisher)
