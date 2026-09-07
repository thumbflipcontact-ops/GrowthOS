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

from app.models.knowledge import BuyingIntent, KnowledgeItem
from app.repositories.knowledge_repository import KnowledgeItemRepository


class KnowledgeBaseClient:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.items = KnowledgeItemRepository(session)

    async def get_by_url(self, project_id: uuid.UUID, url: str) -> KnowledgeItem | None:
        return await self.items.get_by_url(project_id, url)

    async def get(self, item_id: uuid.UUID) -> KnowledgeItem | None:
        """By primary key — what a subscription-triggered agent uses to load the specific
        item its triggering `knowledge_item.created` event refers to (see
        `agents/content_agent/agent.py`), as opposed to `get_by_url`'s dedup-check use case."""
        return await self.items.get(item_id)

    async def upsert_discovery(
        self,
        *,
        project_id: uuid.UUID,
        platform: str,
        url: str,
        tags: list[str],
        confidence: Decimal,
        title: str | None = None,
        body_excerpt: str | None = None,
        platform_metadata: dict | None = None,
        source_agent_run_id: uuid.UUID | None = None,
        buying_intent: BuyingIntent | str | None = None,
        pain_point: str | None = None,
    ) -> tuple[KnowledgeItem, bool]:
        """Writes a newly discovered item, or refreshes the existing row for the same
        `(project_id, url)` in place — see `knowledge_items`' `unique(project_id, url)`
        constraint and docs/jobs/BACKGROUND_JOBS.md's retry-safety note: a retried run
        re-encountering a thread it already wrote must upsert, never raise the unique
        constraint or duplicate the row. Returns `(item, created)` so the caller only
        publishes `knowledge_item.created` for genuinely new rows — re-discovering an
        existing thread with a refreshed score is not a new fact worth another event.

        `title`/`body_excerpt`/`platform_metadata` are opaque grounding text and a
        plugin-specific reference, captured verbatim from the discovery — see
        docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md for why they were added. This
        client never interprets them.

        `buying_intent`/`pain_point` are the LLM-scoring pass's output (see
        agents/conversation_finder/agent.py and prompts.py) — optional because that pass is a
        soft-failing enhancement layer, not every call has them. Left `None` (the model's own
        schema defaults — `BuyingIntent.NONE`/`None`) falls back to exactly this method's
        pre-LLM behavior. `buying_intent` accepts a plain string (the enum's value, e.g.
        `"high"`) as well as a `BuyingIntent` — agents/conversation_finder/agent.py
        deliberately never imports the enum itself (see its own docstring), so this is where
        the plain string `LeadScore.buying_intent` gets converted. `problem`/`industry`/
        `product`/`suggested_*` are still untouched — those remain
        `agents/knowledge_base_agent`'s planned cross-item job, not a per-item extraction
        this method does.
        """
        if buying_intent is not None and not isinstance(buying_intent, BuyingIntent):
            buying_intent = BuyingIntent(buying_intent)

        existing = await self.get_by_url(project_id, url)
        if existing is not None:
            existing.tags = tags
            existing.confidence = confidence
            existing.title = title
            existing.body_excerpt = body_excerpt
            existing.platform_metadata = platform_metadata or {}
            existing.source_agent_run_id = source_agent_run_id
            if buying_intent is not None:
                existing.buying_intent = buying_intent
            if pain_point is not None:
                existing.pain_point = pain_point
            await self.session.flush()
            return existing, False

        item = KnowledgeItem(
            project_id=project_id,
            source_agent_run_id=source_agent_run_id,
            platform=platform,
            url=url,
            tags=tags,
            confidence=confidence,
            title=title,
            body_excerpt=body_excerpt,
            platform_metadata=platform_metadata or {},
            **({"buying_intent": buying_intent} if buying_intent is not None else {}),
            **({"pain_point": pain_point} if pain_point is not None else {}),
        )
        item = await self.items.add(item)
        return item, True
