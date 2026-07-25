"""The common agent interface. See docs/agents/AGENT_ARCHITECTURE.md.

Kept runtime-independent of backend/app (types needed only for static checking are
TYPE_CHECKING-guarded), mirroring plugins/_shared/base.py's dependency discipline — an
agent package should be able to import this module without pulling in the whole backend.

No concrete agent implements this in Phase 1 (Conversation Finder, Content Agent, etc. are
explicitly out of scope — see ROADMAP.md). This is the contract Phase 2 builds against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    import structlog

    from app.core.events import EventPublisher
    from app.core.plugin_registry import PluginRegistry
    from app.models.project import Project


@dataclass(slots=True)
class AgentContext:
    project: "Project"
    config: dict
    plugins: "PluginRegistry"
    # llm and knowledge_base are typed loosely (no concrete class exists yet — AI providers
    # and the knowledge base client are explicitly out of Phase 1 scope, see ROADMAP.md) so
    # this dataclass doesn't reference types that don't exist. Phase 2 tightens these.
    llm: object
    knowledge_base: object
    events: "EventPublisher"
    logger: "structlog.stdlib.BoundLogger"


@dataclass(slots=True)
class AgentResult:
    knowledge_items_created: int = 0
    content_items_created: int = 0
    summary: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Agent(Protocol):
    key: str
    config_schema: type[BaseModel]

    async def run(self, ctx: AgentContext) -> AgentResult: ...
