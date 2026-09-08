"""Monthly usage caps — the cost-safety gate on top of app/core/entitlements.py's
subscription check. See docs/billing/BILLING_ARCHITECTURE.md.

`is_org_entitled` only answers "is this org allowed to use paid features at all" — it says
nothing about *how much* of that a single project has already caused this month. Every
conversation_finder run and every content_agent draft makes a real, metered Anthropic API
call (see agents/conversation_finder/prompts.py's batched lead-scoring call and
agents/content_agent/agent.py's per-item drafting call); without a hard ceiling here, one
project on a flat-price plan can keep generating those calls indefinitely. That's a real risk
for a subscription (which at least keeps charging monthly), and a much worse one for a
one-time-payment plan (a lifetime deal, e.g. AppSumo) — the revenue is fixed the moment it's
paid, but the Anthropic cost is not.

Deliberately one unified cap on `agent_runs` rows, not a separate cap per agent — matches
app/services/agent_config.py's own "no agent-specific code here or ever should be" rule for
platform-wide floors/ceilings, and one AgentRun row already corresponds to (at most) one
metered LLM call for either agent this codebase has today (conversation_finder's batched
scoring call, or content_agent's single drafting call), so counting runs is a fair proxy for
total LLM spend regardless of which agent caused them.

Counts existing `agent_runs` rows directly rather than maintaining a separate running
counter — simpler, always consistent with the actual audit trail (docs/jobs/
BACKGROUND_JOBS.md's "Observability" section), and cheap at this project's current scale (an
indexed, project-scoped COUNT, not a full-table scan).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRun

# Deliberately generous relative to the new once-daily default schedule (~30 scheduled
# conversation_finder runs/month on its own) — this is a hard ceiling against misuse or
# misconfiguration (repeated manual "Run now" clicks, or a much broader keyword list causing
# many more content_agent drafting runs than usual), not a limit normal usage should ever
# brush up against. Revisit once real per-run Anthropic cost is measured and actual pricing
# tiers (e.g. an AppSumo lifetime deal) are modeled against it.
MAX_AGENT_RUNS_PER_MONTH = 300


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def runs_this_month(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Every `agent_runs` row for `project_id` created since the start of the current
    calendar month (UTC), regardless of `agent_key` or `status` — an attempt that failed or
    was skipped still made whatever LLM call it made before failing, so it still counts."""
    result = await session.execute(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.project_id == project_id, AgentRun.created_at >= _month_start())
    )
    return result.scalar_one()


async def has_reached_run_cap(session: AsyncSession, project_id: uuid.UUID) -> bool:
    return await runs_this_month(session, project_id) >= MAX_AGENT_RUNS_PER_MONTH


__all__ = ["MAX_AGENT_RUNS_PER_MONTH", "has_reached_run_cap", "runs_this_month"]
