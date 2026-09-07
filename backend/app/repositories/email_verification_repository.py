from __future__ import annotations

from sqlalchemy import select

from app.models.email_verification import EmailVerificationToken
from app.repositories.base import Repository


class EmailVerificationTokenRepository(Repository[EmailVerificationToken]):
    model = EmailVerificationToken

    async def get_by_hash(self, token_hash: str) -> EmailVerificationToken | None:
        result = await self.session.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()
