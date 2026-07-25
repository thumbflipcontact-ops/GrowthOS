"""The common agent interface. See docs/agents/AGENT_ARCHITECTURE.md.

Kept runtime-independent of backend/app (types needed only for static checking are
TYPE_CHECKING-guarded), mirroring plugins/_shared/base.py's dependency discipline — an
agent package should be able to import this module without pulling in the whole backend.

Phase 2A (docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md) is the first concrete
agent built against this contract — `knowledge_base` is now typed to the concrete
`KnowledgeBaseClient` rather than `object`. `llm` stays loosely typed: no LLM provider client
exists yet (explicitly out of Phase 2A scope, see ROADMAP.md).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    import structlog

    from app.core.events import EventPublisher
    from app.core.plugin_registry import PluginRegistry
    from app.models.project import Project
    from app.services.knowledge_base import KnowledgeBaseClient


@dataclass(slots=True)
class AgentContext:
    project: "Project"
    config: dict
    plugins: "PluginRegistry"
    # llm stays typed loosely (object) — no LLM provider client exists yet, explicitly out
    # of Phase 2A scope, see ROADMAP.md and the config_schema fields conversation_finder
    # deliberately leaves unpopulated (README.md §"What Phase 2A does not do").
    llm: object
    knowledge_base: "KnowledgeBaseClient"
    events: "EventPublisher"
    logger: "structlog.stdlib.BoundLogger"
    # The agent_runs row this context was built for, if any — set by the job runner
    # (app/jobs/agent_runs.py) once that row exists, so an agent can stamp
    # knowledge_items.source_agent_run_id. None for a context built outside a real run (e.g.
    # a unit test constructing AgentContext directly).
    agent_run_id: "uuid.UUID | None" = None


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
