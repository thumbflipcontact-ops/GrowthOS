from __future__ import annotations

from sqlalchemy import select

from app.models.password_reset import PasswordResetToken
from app.repositories.base import Repository


class PasswordResetTokenRepository(Repository[PasswordResetToken]):
    model = PasswordResetToken

    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        result = await self.session.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()
