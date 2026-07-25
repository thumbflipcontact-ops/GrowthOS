from __future__ import annotations

from agents.content_agent.subscriptions import AGENT_SUBSCRIPTIONS


def test_content_agent_subscribes_to_knowledge_item_created() -> None:
    assert AGENT_SUBSCRIPTIONS.agent_key == "content_agent"
    assert len(AGENT_SUBSCRIPTIONS.subscriptions) == 1
    assert AGENT_SUBSCRIPTIONS.subscriptions[0].event_type == "knowledge_item.created"


def test_matches_any_knowledge_item_created_payload_regardless_of_buying_intent() -> None:
    """No buying_intent filter — see subscriptions.py's docstring and README.md for why."""
    assert AGENT_SUBSCRIPTIONS.matches("knowledge_item.created", {"buying_intent": "none"})
    assert AGENT_SUBSCRIPTIONS.matches("knowledge_item.created", {"buying_intent": "high"})
    assert AGENT_SUBSCRIPTIONS.matches("knowledge_item.created", {})


def test_does_not_match_a_different_event_type() -> None:
    assert AGENT_SUBSCRIPTIONS.matches("content_item.published", {}) is False
