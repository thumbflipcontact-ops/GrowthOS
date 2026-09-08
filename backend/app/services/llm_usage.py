"""`AgentContext.usage` — records the real, measured cost of an LLM completion. See
app/models/llm_usage.py for why this table exists and app/core/llm/pricing.py for how the
dollar figure is computed.

Added alongside `KnowledgeBaseClient`/`ContentDraftClient` in `AgentContext` (see
agents/_shared/base.py) — every agent-triggered LLM call records through this the same way
every discovery goes through `KnowledgeBaseClient`. `keyword_suggestion_service.py` isn't an
agent and has no `AgentContext`, so it constructs this client directly instead — see its own
call site in app/api/v1/keyword_suggestions.py.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.base import CompletionResult
from app.core.llm.pricing import estimate_cost_usd
from app.models.llm_usage import LlmUsageLog


class LlmUsageClient:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        purpose: str,
        result: CompletionResult,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        """A `CompletionResult` with no token counts (a provider that doesn't report usage,
        or a test double) is silently skipped rather than logged as a zero-cost call — a
        missing figure must never be mistaken for a real, measured zero."""
        if result.input_tokens is None or result.output_tokens is None:
            return

        self.session.add(
            LlmUsageLog(
                org_id=org_id,
                project_id=project_id,
                purpose=purpose,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=estimate_cost_usd(
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                ),
                agent_run_id=agent_run_id,
            )
        )
        await self.session.flush()
