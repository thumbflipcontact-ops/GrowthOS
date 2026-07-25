"""See ARCHITECTURE.md §7 and docs/agents/AGENT_ARCHITECTURE.md §Communication."""

from __future__ import annotations

from agents._shared.subscriptions import AgentSubscriptions, EventSubscription


def test_subscription_with_no_filter_matches_any_payload() -> None:
    sub = EventSubscription(event_type="knowledge_item.created")
    assert sub.matches({"anything": "goes"}) is True


def test_subscription_filter_accepts_matching_payload() -> None:
    sub = EventSubscription(
        event_type="knowledge_item.created",
        filter=lambda p: p.get("buying_intent") in ("medium", "high"),
    )
    assert sub.matches({"buying_intent": "high"}) is True


def test_subscription_filter_rejects_non_matching_payload() -> None:
    sub = EventSubscription(
        event_type="knowledge_item.created",
        filter=lambda p: p.get("buying_intent") in ("medium", "high"),
    )
    assert sub.matches({"buying_intent": "low"}) is False


def test_agent_subscriptions_matches_by_event_type_and_filter() -> None:
    subs = AgentSubscriptions(
        agent_key="content_agent",
        subscriptions=(
            EventSubscription("knowledge_item.created", filter=lambda p: p.get("buying_intent") == "high"),
            EventSubscription("contact.followup_due"),
        ),
    )
    assert subs.matches("knowledge_item.created", {"buying_intent": "high"}) is True
    assert subs.matches("knowledge_item.created", {"buying_intent": "low"}) is False
    assert subs.matches("contact.followup_due", {}) is True
    assert subs.matches("content_item.published", {}) is False


def test_agent_subscriptions_empty_tuple_matches_nothing() -> None:
    subs = AgentSubscriptions(agent_key="conversation_finder")
    assert subs.matches("knowledge_item.created", {}) is False
