"""Per-call LLM spend log — the actual, measured Anthropic cost of every completion this
platform makes, not an estimate. Exists so a real per-org/per-project cost figure is queryable
(e.g. `select org_id, sum(cost_usd) from llm_usage_logs group by org_id`) ahead of pricing
decisions like the AppSumo LTD tier — see Organization.is_ltd and
app/core/usage_limits.py's own note on why an LTD org gets a tighter run cap: this table is
what lets that assumption be checked against reality instead of an estimate.

Write-only from the caller's perspective — see app/services/llm_usage.py's LlmUsageClient,
the only thing that ever inserts a row here. Nothing in the product reads this table today;
it's purely for an operator to query directly (the same Railway-SSH-diagnostic-script pattern
already used throughout this project) or, later, an admin-only reporting view.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin


class LlmUsageLog(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "llm_usage_logs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Free-form, not a closed enum — same reasoning as LtdCode.source: a new call site (a
    # future agent, a future service) should be able to log under a new purpose string without
    # a migration. Current values: "conversation_finder.lead_scoring",
    # "content_agent.draft_reply", "keyword_suggestion".
    purpose: Mapped[str] = mapped_column(nullable=False)
    # The API-reported model id (e.g. "claude-sonnet-4-5-20250929"), not the configured alias
    # (Settings.anthropic_model) — see app/core/llm/pricing.py's prefix-match note on why these
    # can differ and why that's fine for cost lookup.
    model: Mapped[str] = mapped_column(nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)
    # Computed once at write time from app/core/llm/pricing.py's rate table and stored, not
    # recomputed on read — so a later price-table change never silently rewrites the historical
    # cost of a call that already happened.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    # Only set for an agent-triggered call (conversation_finder/content_agent) — NULL for
    # keyword_suggestion, which has no agent_runs row. ON DELETE SET NULL: the run being
    # deleted (see settings/agents/page.tsx's run-history delete) shouldn't take the cost
    # record of the money already spent with it.
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
