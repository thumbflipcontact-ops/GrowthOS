"""Cost-control sweep for agents that spend real, metered plugin API calls — currently just
`conversation_finder`. Deliberately separated from app/jobs/agent_lifecycle.py's Arq periodic-
job wrapper, the same pattern app/core/oauth/refresh.py's OAuthRefreshSweep uses, so this runs
and is tested as plain async/await against a real session, without a running Arq worker.

Two independent reasons an enabled conversation_finder config gets disabled:
- Nobody in the org has logged in for INACTIVITY_THRESHOLD.
- The org is no longer entitled (is_org_entitled — trial ended without subscribing, or a
  subscription that's canceled/past_due), covering more than just "trial expired" since all of
  those states should equally stop paying for X API calls on the org's behalf.

`is_comped` orgs are exempt from both — see Organization.is_comped's own docstring: the whole
point of that flag is permanent, unconditional access, which a founder's own testing account
going quiet for 48h shouldn't silently defeat.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email.client import ResendClient
from app.core.email.errors import EmailError, EmailNotConfigured
from app.core.email.templates import (
    conversation_finder_disabled_inactivity,
    conversation_finder_disabled_not_entitled,
)
from app.core.entitlements import is_org_entitled
from app.core.observability import capture_exception
from app.models.agent import AgentConfig
from app.models.identity import Organization
from app.models.project import Project
from app.repositories.agent_repository import AgentConfigRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import MembershipRepository
from app.services.agent_config import AgentConfigService

logger = structlog.get_logger()

CONVERSATION_FINDER_AGENT_KEY = "conversation_finder"
INACTIVITY_THRESHOLD = timedelta(hours=48)


@dataclass
class _OrgState:
    organization: Organization
    is_entitled: bool
    most_recent_login_at: datetime


class AgentLifecycleSweep:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.configs = AgentConfigRepository(session)
        self.organizations = OrganizationRepository(session)
        self.memberships = MembershipRepository(session)

    async def run(self, *, now: datetime | None = None) -> int:
        """Disables every enabled conversation_finder config whose org is either not entitled
        or inactive. Returns the count disabled. Caches org lookups per run so an org with
        several projects sharing conversation_finder doesn't re-query the same org repeatedly."""
        now = now or datetime.now(UTC)
        configs = await self.configs.list_enabled_by_key(CONVERSATION_FINDER_AGENT_KEY)

        org_cache: dict[uuid.UUID, _OrgState | None] = {}
        disabled_count = 0
        for config in configs:
            project = await self.session.get(Project, config.project_id)
            if project is None:
                continue

            org_state = await self._resolve_org_state(project.org_id, org_cache, now)
            if org_state is None or org_state.organization.is_comped:
                continue

            reason = self._disable_reason(org_state, now)
            if reason is None:
                continue

            await self._disable_and_notify(config, project, reason)
            disabled_count += 1

        await self.session.commit()
        return disabled_count

    async def _resolve_org_state(
        self, org_id: uuid.UUID, cache: dict[uuid.UUID, _OrgState | None], now: datetime
    ) -> _OrgState | None:
        if org_id in cache:
            return cache[org_id]

        organization = await self.organizations.get(org_id)
        if organization is None:
            cache[org_id] = None
            return None

        entitled = await is_org_entitled(self.session, org_id)
        # COALESCE against the org's own created_at, never treat a NULL/no-membership result
        # as "ancient" — same philosophy app/core/entitlements.py uses for its own
        # no-card-trial computation off Organization.created_at.
        most_recent_login = await self.memberships.most_recent_login_at(org_id)
        state = _OrgState(
            organization=organization,
            is_entitled=entitled,
            most_recent_login_at=most_recent_login or organization.created_at,
        )
        cache[org_id] = state
        return state

    def _disable_reason(self, org_state: _OrgState, now: datetime) -> str | None:
        if not org_state.is_entitled:
            return "not_entitled"
        if now - org_state.most_recent_login_at > INACTIVITY_THRESHOLD:
            return "inactive"
        return None

    async def _disable_and_notify(
        self, config: AgentConfig, project: Project, reason: str
    ) -> None:
        await AgentConfigService(self.session).upsert(
            project_id=project.id,
            org_id=project.org_id,
            actor_user_id=None,
            agent_key=CONVERSATION_FINDER_AGENT_KEY,
            config=config.config,
            schedule_cron=config.schedule_cron,
            enabled=False,
            action_override="agent_config.auto_disabled",
        )
        logger.info(
            "agent_lifecycle.disabled",
            project_id=str(project.id),
            org_id=str(project.org_id),
            reason=reason,
        )
        await self._notify_org(project, reason)

    async def _notify_org(self, project: Project, reason: str) -> None:
        try:
            client = ResendClient.from_settings(self.settings)
        except EmailNotConfigured:
            logger.warning("agent_lifecycle.email_not_configured", project_id=str(project.id))
            return

        template = (
            conversation_finder_disabled_not_entitled
            if reason == "not_entitled"
            else conversation_finder_disabled_inactivity
        )

        users = await self.memberships.list_users_for_org(project.org_id)
        for user in users:
            subject, html_body = template(user_name=user.name, project_name=project.name)
            try:
                await client.send(to=user.email, subject=subject, html_body=html_body)
            except EmailError as exc:
                # A failed notification must never block the disable it's reporting — the
                # disable already committed by the time this runs.
                logger.warning(
                    "agent_lifecycle.notify_failed",
                    project_id=str(project.id),
                    user_id=str(user.id),
                    error=str(exc),
                )
                capture_exception(exc)


__all__ = ["AgentLifecycleSweep", "CONVERSATION_FINDER_AGENT_KEY", "INACTIVITY_THRESHOLD"]
