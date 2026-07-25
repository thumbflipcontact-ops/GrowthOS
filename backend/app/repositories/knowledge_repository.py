from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.knowledge import KnowledgeItem
from app.repositories.base import Repository


class KnowledgeItemRepository(Repository[KnowledgeItem]):
    model = KnowledgeItem

    async def get_by_url(self, project_id: uuid.UUID, url: str) -> KnowledgeItem | None:
        """The dedup check every discovery agent runs before writing a new row — matches
        knowledge_items' `unique(project_id, url)` constraint exactly. See
        docs/knowledge-base/KNOWLEDGE_BASE.md."""
        result = await self.session.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.project_id == project_id, KnowledgeItem.url == url
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeItem]:
        """Newest-discovered first. `tag` filters via `= ANY(tags)` — the portable ARRAY
        operator the model's plain `sqlalchemy.ARRAY` column type supports (`.contains()`,
        which would map to postgres's GIN-accelerated `@>` operator, requires the
        postgres-dialect ARRAY type, which `knowledge_items.tags` deliberately isn't — see
        models/knowledge.py). At today's data volume `= ANY(...)` is fine; if `tags`
        filtering needs to scale further, switching the column to
        `sqlalchemy.dialects.postgresql.ARRAY` and this filter to `.contains([tag])` would
        let `idx_knowledge_items_tags` actually accelerate it — noted here rather than done
        speculatively, per docs/api/API_DESIGN.md's "a filter that would require a full
        table scan is not exposed until there's an index to back it."""
        stmt = (
            select(KnowledgeItem)
            .where(KnowledgeItem.project_id == project_id)
            .order_by(KnowledgeItem.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if tag is not None:
            # SQLAlchemy's ARRAY.any() stub is typed for a clause element (its usual use is
            # comparing against a correlated subquery); a plain scalar is valid at runtime
            # (renders `tag = ANY(tags)`) but mypy can't see that.
            stmt = stmt.where(KnowledgeItem.tags.any(tag))  # type: ignore[arg-type]
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
