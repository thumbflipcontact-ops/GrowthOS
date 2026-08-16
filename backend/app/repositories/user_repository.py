from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.models.identity import Membership, User
from app.repositories.base import Repository


class UserRepository(Repository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


class MembershipRepository(Repository[Membership]):
    model = Membership

    async def get_by_org_and_user(self, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        result = await self.session.execute(
            select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        result = await self.session.execute(select(Membership).where(Membership.user_id == user_id))
        return list(result.scalars().all())

    async def most_recent_login_at(self, org_id: uuid.UUID) -> datetime | None:
        """MAX(User.last_login_at) across every member of org_id — used by
        app/core/agent_lifecycle.py's 48h-inactivity check so an org with multiple members is
        judged by whichever member logged in most recently, not just one. None only if the org
        somehow has zero memberships."""
        result = await self.session.execute(
            select(func.max(User.last_login_at))
            .select_from(Membership)
            .join(User, Membership.user_id == User.id)
            .where(Membership.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def list_users_for_org(self, org_id: uuid.UUID) -> list[User]:
        """Every member of org_id, for resolving notification recipients (e.g.
        app/core/agent_lifecycle.py's auto-disable emails)."""
        result = await self.session.execute(
            select(User).join(Membership, Membership.user_id == User.id).where(
                Membership.org_id == org_id
            )
        )
        return list(result.scalars().all())
