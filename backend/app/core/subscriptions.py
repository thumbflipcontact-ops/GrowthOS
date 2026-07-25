"""Agent subscription discovery — the event-dispatch-side counterpart to
app/core/plugin_catalog.py. See docs/agents/AGENT_ARCHITECTURE.md §Communication:
"the dispatcher discovers subscribers by scanning installed agent packages, the same
pattern plugins use for discovery."

    # an agent's pyproject.toml
    [project.entry-points."growthos.agents"]
    content_agent = "agents.content_agent.subscriptions:AGENT_SUBSCRIPTIONS"
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable

import structlog
from agents._shared.subscriptions import AgentSubscriptions

logger = structlog.get_logger()

ENTRY_POINT_GROUP = "growthos.agents"


def discover_agent_subscriptions() -> list[AgentSubscriptions]:
    """Mirrors app/core/plugin_catalog.py's discover_installed_plugins(): one bad agent
    package is logged and excluded, never allowed to prevent the rest of the system (or the
    dispatcher itself) from starting."""
    discovered: list[AgentSubscriptions] = []
    for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = entry_point.load()
        except Exception:
            logger.error("agent_discovery.import_failed", agent_key=entry_point.name, exc_info=True)
            continue

        if not isinstance(candidate, AgentSubscriptions):
            logger.error(
                "agent_discovery.invalid_subscriptions",
                agent_key=entry_point.name,
                got=type(candidate).__name__,
            )
            continue

        discovered.append(candidate)

    return discovered


class SubscriptionRegistry:
    """In-process registry of every discovered agent's subscriptions — built once at
    startup, same lifecycle as PluginCatalog."""

    def __init__(self) -> None:
        self._by_agent: dict[str, AgentSubscriptions] = {}

    def refresh(self, subscriptions: Iterable[AgentSubscriptions]) -> None:
        self._by_agent = {s.agent_key: s for s in subscriptions}

    def subscribers_for(self, event_type: str, payload: dict) -> list[str]:
        """Returns the agent_keys whose subscriptions match this event type and payload
        filter — what the dispatcher (app/core/dispatcher.py) enqueues a job for."""
        return [
            agent_key
            for agent_key, subs in self._by_agent.items()
            if subs.matches(event_type, payload)
        ]

    def all(self) -> tuple[AgentSubscriptions, ...]:
        return tuple(self._by_agent.values())
