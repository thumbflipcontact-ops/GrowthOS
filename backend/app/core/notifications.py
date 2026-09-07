"""Emails an org when new AI-drafted replies are ready for review — see
app/core/agent_lifecycle.py's AgentLifecycleSweep, which this deliberately mirrors: a plain,
session-driven sweep class (unit-testable without a running Arq worker), wrapped by a thin
Arq-cron adapter in app/jobs/agent_lifecycle.py. Same recipient resolution (every org member,
via MembershipRepository.list_users_for_org — this codebase has no single "owner" concept to
notify instead) and the same resilience contract: a missing Resend config or one failed send
must never crash the sweep or block any other recipient.

Unlike AgentLifecycleSweep, this has no entitlement gate — it isn't spending money on the
org's behalf, only reporting work the agent pipeline already completed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email.client import ResendClient
from app.core.email.errors import EmailError, EmailNotConfigured
from app.core.email.templates import drafts_ready_for_review
from app.core.observability import capture_exception
from app.models.content import ContentItem
from app.models.project import Project
from app.repositories.content_repository import ContentItemRepository
from app.repositories.user_repository import MembershipRepository

logger = structlog.get_logger()


class DraftReadyNotificationSweep:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.content_items = ContentItemRepository(session)
        self.memberships = MembershipRepository(session)

    async def run(self, *, now: datetime | None = None) -> int:
        """Batches every not-yet-notified pending_review item per project into one email per
        org member, then marks them notified. Returns the count of projects notified about."""
        now = now or datetime.now(UTC)
        items = await self.content_items.list_pending_review_unnotified()

        by_project: dict[uuid.UUID, list[ContentItem]] = defaultdict(list)
        for item in items:
            by_project[item.project_id].append(item)

        notified_projects = 0
        for project_id, project_items in by_project.items():
            project = await self.session.get(Project, project_id)
            if project is None:
                continue
            await self._notify_org(project, count=len(project_items))
            await self.content_items.mark_notified(
                [item.id for item in project_items], now=now
            )
            notified_projects += 1

        await self.session.commit()
        return notified_projects

    async def _notify_org(self, project: Project, *, count: int) -> None:
        try:
            client = ResendClient.from_settings(self.settings)
        except EmailNotConfigured:
            logger.warning("notifications.email_not_configured", project_id=str(project.id))
            return

        approvals_url = f"{self.settings.frontend_origin}/approvals"
        users = await self.memberships.list_users_for_org(project.org_id)
        for user in users:
            subject, html_body = drafts_ready_for_review(
                user_name=user.name,
                project_name=project.name,
                count=count,
                approvals_url=approvals_url,
            )
            try:
                await client.send(to=user.email, subject=subject, html_body=html_body)
            except EmailError as exc:
                # One bad address must never block the rest of the org, or the count-marking
                # that stops this project from being re-notified next sweep.
                logger.warning(
                    "notifications.notify_failed",
                    project_id=str(project.id),
                    user_id=str(user.id),
                    error=str(exc),
                )
                capture_exception(exc)


__all__ = ["DraftReadyNotificationSweep"]
