"""Public-API webhook subscription CRUD — an n8n trigger node registers/unregisters its own
subscription when a workflow is activated/deactivated (n8n's standard
webhookMethods.default.create/.delete pattern), so this must be API-key-authed like every
other /public/v1 route, not dashboard-only. See app/services/webhook_subscription.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_api_key_project
from app.models.api_key import ApiKey
from app.models.project import Project
from app.schemas.webhook import (
    WebhookSubscriptionCreateRequest,
    WebhookSubscriptionCreateResponse,
    WebhookSubscriptionResponse,
)
from app.services.webhook_subscription import WebhookSubscriptionService

router = APIRouter(prefix="/webhook-subscriptions", tags=["public-webhooks"])


@router.post("", response_model=WebhookSubscriptionCreateResponse, status_code=201)
async def create_webhook_subscription(
    body: WebhookSubscriptionCreateRequest,
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
) -> WebhookSubscriptionCreateResponse:
    project, api_key = project_and_key
    record, secret = await WebhookSubscriptionService(session).create(
        project_id=project.id,
        org_id=project.org_id,
        created_by_api_key_id=api_key.id,
        actor_user_id=api_key.created_by_user_id,
        target_url=body.target_url,
        event_types=body.event_types,
    )
    return WebhookSubscriptionCreateResponse(
        id=record.id,
        target_url=record.target_url,
        event_types=record.event_types,
        secret=secret,
        enabled=record.enabled,
        created_at=record.created_at,
    )


@router.get("", response_model=list[WebhookSubscriptionResponse])
async def list_webhook_subscriptions(
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
) -> list[WebhookSubscriptionResponse]:
    project, _api_key = project_and_key
    subs = await WebhookSubscriptionService(session).list_for_project(project.id)
    return [WebhookSubscriptionResponse.model_validate(s) for s in subs]


@router.delete("/{subscription_id}", status_code=204, response_model=None)
async def delete_webhook_subscription(
    subscription_id: uuid.UUID,
    project_and_key: tuple[Project, ApiKey] = Depends(require_api_key_project),
    session: AsyncSession = Depends(get_db),
) -> None:
    project, api_key = project_and_key
    await WebhookSubscriptionService(session).revoke(
        project_id=project.id,
        org_id=project.org_id,
        actor_user_id=api_key.created_by_user_id,
        subscription_id=subscription_id,
    )
