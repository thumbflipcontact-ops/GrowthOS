"""The common agent interface. See docs/agents/AGENT_ARCHITECTURE.md.

Kept runtime-independent of backend/app (types needed only for static checking are
TYPE_CHECKING-guarded), mirroring plugins/_shared/base.py's dependency discipline — an
agent package should be able to import this module without pulling in the whole backend.

Phase 2A (docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md) was the first concrete
agent built against this contract — `knowledge_base` is typed to the concrete
`KnowledgeBaseClient` rather than `object`. Phase 2B
(docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md) tightens `llm` to the concrete
`LLMProvider` the same way, adds `trigger_payload` for subscription-triggered agents, and adds
`content` (`ContentDraftClient`) — this contract never included a `content_items`-writing
client at all until an agent (Content Agent) existed that needed one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    import structlog
    from app.core.events import EventPublisher
    from app.core.llm.base import LLMProvider
    from app.core.plugin_registry import PluginRegistry
    from app.models.project import Project
    from app.services.content_drafts import ContentDraftClient
    from app.services.knowledge_base import KnowledgeBaseClient


@dataclass(slots=True)
class AgentContext:
    project: Project
    config: dict
    plugins: PluginRegistry
    llm: LLMProvider
    knowledge_base: KnowledgeBaseClient
    content: ContentDraftClient
    events: EventPublisher
    logger: structlog.stdlib.BoundLogger
    # The agent_runs row this context was built for, if any — set by the job runner
    # (app/jobs/agent_runs.py / app/jobs/events.py) once that row exists, so an agent can
    # stamp e.g. knowledge_items.source_agent_run_id / content_items.created_by_agent_run_id.
    # None for a context built outside a real run (e.g. a unit test constructing
    # AgentContext directly).
    agent_run_id: uuid.UUID | None = None
    # The specific domain event's payload that triggered this run, for a subscription-
    # triggered agent (e.g. content_agent reacting to knowledge_item.created) — see
    # docs/agents/AGENT_ARCHITECTURE.md §Communication: "reading only the specific item the
    # event refers to," not polling. None for a schedule-triggered agent (e.g.
    # conversation_finder), which has no single triggering event.
    trigger_payload: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentResult:
    knowledge_items_created: int = 0
    content_items_created: int = 0
    summary: dict = field(default_factory=dict)
    # Customer-visible — rendered on that project's own Agent settings page (see
    # frontend/app/settings/agents/page.tsx), so these must only ever describe something
    # actionable by that customer or genuinely specific to their own connection.
    errors: list[str] = field(default_factory=list)
    # Operator-visible only, never rendered to a customer — for failures that are the
    # platform's problem, not theirs (e.g. the platform's own shared X app running out of
    # pay-per-use credits), where showing the raw detail to a customer would be both
    # confusing (implies their connection is broken when it isn't) and not actionable by
    # them. The job runner (app/jobs/agent_runs.py) forwards these to error tracking.
    operator_alerts: list[str] = field(default_factory=list)


class Agent(Protocol):
    key: str
    config_schema: type[BaseModel]

    async def run(self, ctx: AgentContext) -> AgentResult: ...
