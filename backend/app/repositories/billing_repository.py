from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.billing import Subscription
from app.repositories.base import Repository


class SubscriptionRepository(Repository[Subscription]):
    model = Subscription

    async def get_by_org(self, org_id: uuid.UUID) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        """Every subscription row ever created, regardless of status — the tiered-pricing
        "signup order" counter (see app/core/pricing.py). Deliberately includes canceled rows:
        a founding-tier org that later cancels doesn't free up its spot for someone else, the
        same way the price itself stays permanent for that org."""
        result = await self.session.execute(select(func.count()).select_from(Subscription))
        return result.scalar_one()

    async def get_by_polar_subscription_id(self, polar_subscription_id: str) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.polar_subscription_id == polar_subscription_id)
        )
        return result.scalar_one_or_none()
