"""The first concrete implementation of `AgentContext.content` — the drafting-side
counterpart to `KnowledgeBaseClient`. See docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md.

`AgentContext` didn't originally include a `content_items`-writing client at all
(docs/agents/AGENT_ARCHITECTURE.md's documented shape predates any agent that wrote
`content_items`) — Content Agent (Phase 2B) is the first, so this is that first client,
added the same way `KnowledgeBaseClient` was added in Phase 2A. Every row this client
creates defaults to `status="draft"` (the model's own schema default) and nothing in this
client — or anywhere in Content Agent's own code — ever changes that. Advancing a draft to
`pending_review`/`approved`/`published` is `ContentApprovalService`'s job, not built yet
(Phase 2C).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.repositories.content_repository import ContentItemRepository


class ContentDraftClient:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = ContentItemRepository(session)

    async def create_draft(
        self,
        *,
        project_id: uuid.UUID,
        type: str,
        body: str,
        confidence: Decimal,
        reasoning: str | None = None,
        evidence: list[str] | None = None,
        target_platform: str | None = None,
        target_ref: str | None = None,
        knowledge_item_id: uuid.UUID | None = None,
        source_agent_run_id: uuid.UUID | None = None,
    ) -> ContentItem:
        item = ContentItem(
            project_id=project_id,
            type=type,
            body=body,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence or [],
            target_platform=target_platform,
            target_ref=target_ref,
            knowledge_item_id=knowledge_item_id,
            created_by_agent_run_id=source_agent_run_id,
            # status is deliberately not set here — the model's own default (`draft`) is the
            # only status any agent-created row is ever written with.
        )
        return await self.items.add(item)
