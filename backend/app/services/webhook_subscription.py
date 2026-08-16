"""Create/list/revoke a project's outbound webhook subscriptions. See
app/api/public/v1/webhooks.py (the only routes that call this — API-key-authed, since an n8n
trigger node registers/unregisters its own subscription when a workflow is
activated/deactivated, the same pattern n8n's webhookMethods.default.create/.delete expects)
and app/core/webhooks/dispatcher.py (the only thing that reads `secret`/`target_url` again
after creation).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.webhooks.validation import validate_target_url
from app.models.audit import AuditLog
from app.models.webhook import WebhookSubscription
from app.repositories.webhook_repository import WebhookSubscriptionRepository

# The only event this pass supports — see plan's "explicitly out of scope" section. Validated
# here so a typo'd or aspirational event_types entry fails loudly at creation, not silently at
# dispatch time.
SUPPORTED_EVENT_TYPES = frozenset({"conversation.discovered"})


class WebhookSubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscriptions = WebhookSubscriptionRepository(session)

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        created_by_api_key_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        target_url: str,
        event_types: list[str],
    ) -> tuple[WebhookSubscription, str]:
        validate_target_url(target_url)
        unknown = set(event_types) - SUPPORTED_EVENT_TYPES
        if unknown:
            raise ValidationError(
                f"Unsupported event_types: {sorted(unknown)!r}.",
                details={"supported": sorted(SUPPORTED_EVENT_TYPES)},
            )

        secret = secrets.token_urlsafe(32)
        record = WebhookSubscription(
            project_id=project_id,
            created_by_api_key_id=created_by_api_key_id,
            target_url=target_url,
            event_types=event_types,
            secret=secret,
        )
        self.session.add(record)
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="webhook_subscription.created",
                target=str(record.id),
            )
        )
        await self.session.flush()
        return record, secret

    async def list_for_project(self, project_id: uuid.UUID) -> list[WebhookSubscription]:
        return await self.subscriptions.list_by_project(project_id)

    async def revoke(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        subscription_id: uuid.UUID,
    ) -> None:
        record = await self.subscriptions.get_scoped(project_id, subscription_id)
        if record is None:
            raise NotFoundError(
                "Webhook subscription not found.", details={"subscription_id": str(subscription_id)}
            )
        record.enabled = False
        record.revoked_at = datetime.now(UTC)
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="webhook_subscription.revoked",
                target=str(record.id),
            )
        )
        await self.session.flush()
