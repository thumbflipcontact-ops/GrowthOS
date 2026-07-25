"""Conversation Finder is schedule-only — it originates a discovery cycle rather than
reacting to one, so it has nothing to subscribe to. See
agents/_shared/subscriptions.py and docs/agents/AGENT_ARCHITECTURE.md §"Scheduling vs.
subscription".
"""

from __future__ import annotations

from agents._shared.subscriptions import AgentSubscriptions

AGENT_SUBSCRIPTIONS = AgentSubscriptions(agent_key="conversation_finder", subscriptions=())
