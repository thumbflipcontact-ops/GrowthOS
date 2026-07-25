from __future__ import annotations

from agents.conversation_finder.subscriptions import AGENT_SUBSCRIPTIONS


def test_conversation_finder_is_schedule_only() -> None:
    """Schedule-only means an empty subscriptions tuple — see subscriptions.py and
    docs/agents/AGENT_ARCHITECTURE.md §"Scheduling vs. subscription"."""
    assert AGENT_SUBSCRIPTIONS.agent_key == "conversation_finder"
    assert AGENT_SUBSCRIPTIONS.subscriptions == ()


def test_matches_nothing() -> None:
    assert AGENT_SUBSCRIPTIONS.matches("knowledge_item.created", {"buying_intent": "high"}) is False
    assert AGENT_SUBSCRIPTIONS.matches("anything", {}) is False
