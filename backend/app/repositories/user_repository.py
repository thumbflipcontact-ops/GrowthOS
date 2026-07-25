from __future__ import annotations

import uuid

from sqlalchemy import select

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
