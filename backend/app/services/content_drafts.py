"""The first concrete implementation of `AgentContext.content` — the drafting-side
counterpart to `KnowledgeBaseClient`. See
docs/reviews/APPROVAL_WORKFLOW_IMPLEMENTATION_REPORT.md.

`AgentContext` didn't originally include a `content_items`-writing client at all
(docs/agents/AGENT_ARCHITECTURE.md's documented shape predates any agent that wrote
`content_items`) — Content Agent (Phase 2B) is the first, so this is that first client,
added the same way `KnowledgeBaseClient` was added in Phase 2A.

`create_draft` writes every row as `status="draft"` (the model's own schema default) —
nothing about *this method* ever writes any other status; that guarantee is unchanged from
Phase 2B. `submit_for_review` (Phase 2C) is a separate, explicit second step matching
ARCHITECTURE.md §8's "always created in draft, immediately auto-advanced to pending_review
once the agent's own self-check passes" — an agent calls it right after `create_draft`, not
instead of it. Advancing a review-ready item to `approved`/`rejected`/`archived` is
`ContentApprovalService`'s job (a human decision, never automatic); advancing `approved` to
`published` is the publish worker's job. Neither happens in this file.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.content import ContentItem, ContentItemStatus
from app.repositories.content_repository import ContentItemRepository
from app.services.content_self_check import SelfCheckResult, run_self_check


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

    async def submit_for_review(
        self,
        item: ContentItem,
        *,
        org_id: uuid.UUID,
        max_length: int,
        banned_phrases: Sequence[str] = (),
    ) -> SelfCheckResult:
        """Runs the self-check (`app/services/content_self_check.py`) against `item.body`
        and, if it passes, advances `item.status` from `draft` to `pending_review` in place
        — never touching `reviewed_by_user_id`/`reviewed_at` (those mean "a human reviewed
        this," which this automatic step is not, per the `review_fields_consistent`
        constraint's own stated purpose). A failing check leaves `item` in `draft` — the
        reasons are returned, not stored on the row itself; the caller (an agent's `run()`)
        is expected to put them in `AgentResult.summary`, the same way every other
        "why didn't this happen" signal in this codebase is surfaced (see
        docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md's analogous pattern).

        Writes an `audit_log` row only when the check passes (`actor_user_id=None` — this is
        a system action, not a human one) — a failed check that leaves the item exactly
        where it already was isn't a state transition worth auditing.
        """
        check = run_self_check(item.body, max_length=max_length, banned_phrases=banned_phrases)
        if check.passed:
            item.status = ContentItemStatus.PENDING_REVIEW
            await self.session.flush()
            self.session.add(
                AuditLog(
                    org_id=org_id,
                    actor_user_id=None,
                    action="content_item.submitted_for_review",
                    target=str(item.id),
                )
            )
            await self.session.flush()
        return check
