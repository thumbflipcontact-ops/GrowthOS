"""The first concrete implementation of `AgentContext.knowledge_base`. See
docs/knowledge-base/KNOWLEDGE_BASE.md and docs/agents/AGENT_ARCHITECTURE.md.

backend/README.md previously listed this file under "Explicitly not present" — Conversation
Finder (Phase 2A, see docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md) is the first
agent that needs to write `knowledge_items`, so this is that first concrete client. An agent
never touches `KnowledgeItemRepository` or the ORM model directly — only this client, so the
dedup-then-write convention lives in exactly one place rather than being re-implemented by
every future discovery agent.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeItem
from app.repositories.knowledge_repository import KnowledgeItemRepository


class KnowledgeBaseClient:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = KnowledgeItemRepository(session)

    async def get_by_url(self, project_id: uuid.UUID, url: str) -> KnowledgeItem | None:
        return await self.items.get_by_url(project_id, url)

    async def upsert_discovery(
        self,
        *,
        project_id: uuid.UUID,
        platform: str,
        url: str,
        tags: list[str],
        confidence: Decimal,
        source_agent_run_id: uuid.UUID | None = None,
    ) -> tuple[KnowledgeItem, bool]:
        """Writes a newly discovered item, or refreshes the existing row for the same
        `(project_id, url)` in place — see `knowledge_items`' `unique(project_id, url)`
        constraint and docs/jobs/BACKGROUND_JOBS.md's retry-safety note: a retried run
        re-encountering a thread it already wrote must upsert, never raise the unique
        constraint or duplicate the row. Returns `(item, created)` so the caller only
        publishes `knowledge_item.created` for genuinely new rows — re-discovering an
        existing thread with a refreshed score is not a new fact worth another event.

        Deliberately does not touch `problem`/`industry`/`product`/`pain_point`/
        `buying_intent`/`suggested_*` — those are LLM-derived fields with no extraction step
        yet (Phase 2A has no LLM integration, see ROADMAP.md); they stay at the model's
        schema defaults until a future enrichment pass populates them.
        """
        existing = await self.get_by_url(project_id, url)
        if existing is not None:
            existing.tags = tags
            existing.confidence = confidence
            existing.source_agent_run_id = source_agent_run_id
            await self.session.flush()
            return existing, False

        item = KnowledgeItem(
            project_id=project_id,
            source_agent_run_id=source_agent_run_id,
            platform=platform,
            url=url,
            tags=tags,
            confidence=confidence,
        )
        item = await self.items.add(item)
        return item, True
