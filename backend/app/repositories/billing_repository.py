from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.billing import Subscription
from app.repositories.base import Repository


class SubscriptionRepository(Repository[Subscription]):
    model = Subscription

    async def get_by_org(self, org_id: uuid.UUID) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_polar_subscription_id(self, polar_subscription_id: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == polar_subscription_id)
        )
        return result.scalar_one_or_none()
