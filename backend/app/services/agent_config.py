"""Create/update a project's `agent_configs` row. See docs/api/API_DESIGN.md and
docs/agents/AGENT_ARCHITECTURE.md.

Mirrors app/services/plugin_connection.py's shape: validate the submitted `config` against
the target agent's own `config_schema` — resolved dynamically via
app/core/agent_registry.load_agent, exactly like a plugin connection's config is validated
against `PluginCatalog.get(plugin_key).config_schema` — before writing anything. No
agent-specific code here or ever should be; a second agent (content_agent, Phase 2B) needs no
changes to this file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from croniter import croniter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_registry import load_agent
from app.core.errors import ValidationError
from app.models.agent import AgentConfig
from app.models.audit import AuditLog
from app.repositories.agent_repository import AgentConfigRepository

# The floor on how often any schedule-triggered agent may run, platform-wide — not
# agent-specific (deliberately: this file's own docstring rule is "no agent-specific code
# here or ever should be"). Originally set to 6 hours because X's pay-per-use search pricing
# (see plugins/twitter/README.md) meant an unbounded schedule_cron let one customer's cost
# scale past what a flat subscription price covers, then lowered to 30 minutes after the
# Reddit pivot since Reddit's public search itself has no per-call monetary cost (just a tight
# shared rate limit — see plugins/reddit/plugin.py's _PUBLIC_RATE_LIMITER).
#
# Raised back up to 24 hours for a different reason than either of those: every run still
# makes a real, metered Anthropic API call regardless of which platform plugin it searches
# (agents/conversation_finder/prompts.py's batched lead-scoring pass), and that cost is now
# the binding constraint again — not Reddit's rate limit, but the ceiling on what a flat
# subscription (and especially a one-time-payment plan, e.g. an AppSumo-style lifetime deal,
# where the cost keeps recurring forever after a single fixed payment) can safely absorb.
# Once every 24 hours caps the *automatic* schedule at roughly 30 LLM calls/month/project on
# its own; see app/core/usage_limits.py for the separate hard ceiling that also covers manual
# "Run now" clicks and content_agent's per-lead drafting calls, which this floor alone doesn't
# bound. If a paid-API plugin (X, LinkedIn) is ever reconnected for real customers, this floor
# needs revisiting for that plugin's own cost reasons too.
MINIMUM_SCHEDULE_INTERVAL_SECONDS = 24 * 60 * 60


def _validate_cron(cron_expression: str) -> None:
    """Raises ValidationError for syntactically invalid cron, or one that would fire more
    often than MINIMUM_SCHEDULE_INTERVAL_SECONDS allows. Both checks belong here, at write
    time: app/core/scheduler.py's tick() loops over every enabled schedule across every
    project with no per-config error isolation, so a syntactically invalid cron_expression
    that reached the database would crash the scheduler for every project, not just the one
    that submitted it — validating here is what keeps that failure mode structurally
    impossible rather than merely unlikely."""
    now = datetime.now(UTC)
    try:
        itr = croniter(cron_expression, now)
        fire_times = [itr.get_next(datetime) for _ in range(5)]
    except ValueError as exc:
        raise ValidationError(f"Invalid cron expression: {cron_expression!r}.") from exc

    gaps = [
        (fire_times[i + 1] - fire_times[i]).total_seconds() for i in range(len(fire_times) - 1)
    ]
    smallest_gap = min(gaps)
    if smallest_gap < MINIMUM_SCHEDULE_INTERVAL_SECONDS:
        raise ValidationError(
            f"schedule_cron {cron_expression!r} fires as often as every "
            f"{smallest_gap / 3600:.1f} hours — the minimum allowed interval is "
            f"{MINIMUM_SCHEDULE_INTERVAL_SECONDS // 3600} hours.",
            details={
                "cron_expression": cron_expression,
                "smallest_gap_seconds": smallest_gap,
                "minimum_interval_seconds": MINIMUM_SCHEDULE_INTERVAL_SECONDS,
            },
        )


class AgentConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.configs = AgentConfigRepository(session)

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        agent_key: str,
        config: dict,
        schedule_cron: str | None,
        enabled: bool,
        action_override: str | None = None,
    ) -> AgentConfig:
        agent = load_agent(agent_key)  # raises NotFoundError (404) for an unknown agent_key
        try:
            agent.config_schema.model_validate(config)
        except PydanticValidationError as exc:
            raise ValidationError(
                f"Config does not match agent {agent_key!r}'s config_schema.",
                details={"agent_key": agent_key, "errors": exc.errors()},
            ) from exc

        existing = await self.configs.get_by_project_and_key(project_id, agent_key)
        is_update = existing is not None

        # Only validate a schedule_cron that's actually new or changing — not one already
        # stored as-is. Without this, tightening MINIMUM_SCHEDULE_INTERVAL_SECONDS (as
        # happened going from 30 minutes to 24 hours) would break every *other* field update
        # for a project whose cron predates the change: this method is also how
        # app/core/agent_lifecycle.py's sweep disables an inactive project, and it always
        # round-trips the project's existing schedule_cron unchanged — re-validating it there
        # would raise on a value that was perfectly valid when the customer first saved it.
        if schedule_cron is not None and (existing is None or existing.schedule_cron != schedule_cron):
            _validate_cron(schedule_cron)

        record = existing or AgentConfig(project_id=project_id, agent_key=agent_key)
        record.config = config
        record.schedule_cron = schedule_cron
        record.enabled = enabled
        if not is_update:
            self.session.add(record)
        await self.session.flush()
        if is_update:
            # updated_at's value comes from onupdate=func.now() — a server-side SQL
            # expression, not a Python-computed one. For a fresh INSERT, asyncpg's implicit
            # RETURNING populates server_default columns onto the object automatically, but
            # that doesn't extend to an UPDATE's onupdate value, so without this the attribute
            # is left expired: FastAPI's response serialization (which runs outside this
            # method, once the request's async context has moved on) then can't lazily load
            # it and raises MissingGreenlet — this is exactly what happened on every
            # config-that-already-existed save, i.e. every save after the first.
            await self.session.refresh(record)

        # See CONTRIBUTING.md's plugin-connection precedent (app/services/plugin_connection.py):
        # any project-scoped config write gets an audit_log row — actor_user_id is None only
        # for system-triggered writes (app/core/agent_lifecycle.py's cost-control sweep
        # disabling an agent with no human actor), matching the AuditLog.actor_user_id=None
        # precedent already used by app/jobs/publish.py for its own system-triggered rows.
        # action_override lets that same caller record "agent_config.auto_disabled" instead of
        # the default "agent_config.updated", without changing behavior for any other caller.
        default_action = "agent_config.updated" if is_update else "agent_config.created"
        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action=action_override or default_action,
                target=agent_key,
            )
        )
        await self.session.flush()
        return record

    async def list_for_project(self, project_id: uuid.UUID) -> list[AgentConfig]:
        return await self.configs.list_by_project(project_id)
