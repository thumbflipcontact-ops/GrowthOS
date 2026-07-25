"""Event subscriptions — how an agent declares what it reacts to. See ARCHITECTURE.md §7,
docs/agents/AGENT_ARCHITECTURE.md §Communication, and
docs/decisions/0006-event-driven-agent-communication.md.

An agent package exposes a module-level `SUBSCRIPTIONS: tuple[EventSubscription, ...]`
(conventionally in `agents/<name>/subscriptions.py`), discovered the same way plugins are —
via a `growthos.agents` entry point pointing at it. A schedule-only agent (nothing upstream
to react to, e.g. the one that originates a discovery cycle) simply declares an empty tuple.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EventSubscription:
    event_type: str
    filter: Callable[[dict], bool] | None = None

    def matches(self, payload: dict) -> bool:
        return self.filter is None or self.filter(payload)


@dataclass(frozen=True, slots=True)
class AgentSubscriptions:
    """The discovered unit: one agent's complete set of subscriptions."""

    agent_key: str
    subscriptions: tuple[EventSubscription, ...] = field(default_factory=tuple)

    def matches(self, event_type: str, payload: dict) -> bool:
        return any(sub.event_type == event_type and sub.matches(payload) for sub in self.subscriptions)
