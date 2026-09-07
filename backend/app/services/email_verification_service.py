"""Email verification — see app/api/v1/auth.py's /auth/register (sends the email) and
/auth/verify-email (consumes the token) routes, and app/models/email_verification.py.

Unlike password reset, there's no "don't reveal whether the email exists" concern here — the
caller just registered this exact address, so there's nothing to enumerate.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_keys import hash_api_key
from app.core.email.client import ResendClient
from app.core.email.errors import EmailError, EmailNotConfigured
from app.core.email.templates import email_verification_requested
from app.core.errors import AuthenticationError
from app.models.email_verification import EmailVerificationToken
from app.models.identity import User
from app.repositories.email_verification_repository import EmailVerificationTokenRepository
from app.repositories.user_repository import UserRepository

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger()

_TOKEN_TTL = timedelta(hours=24)


class EmailVerificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = EmailVerificationTokenRepository(session)

    async def send_verification_email(self, *, user: User) -> None:
        full_token = secrets.token_urlsafe(32)
        record = EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_api_key(full_token),
            expires_at=datetime.now(UTC) + _TOKEN_TTL,
        )
        await self.tokens.add(record)

        verify_url = f"{self.settings.frontend_origin}/verify-email?token={full_token}"
        subject, html_body = email_verification_requested(
            user_name=user.name, verify_url=verify_url
        )

        try:
            client = ResendClient.from_settings(self.settings)
        except EmailNotConfigured:
            logger.warning("email_verification.email_not_configured", user_id=str(user.id))
            return
        try:
            await client.send(to=user.email, subject=subject, html_body=html_body)
        except EmailError as exc:
            logger.warning(
                "email_verification.email_send_failed", user_id=str(user.id), error=str(exc)
            )

    async def verify(self, *, token: str) -> User:
        record = await self.tokens.get_by_hash(hash_api_key(token))
        now = datetime.now(UTC)
        if record is None or record.used_at is not None or record.expires_at < now:
            raise AuthenticationError("Invalid or expired verification link.")

        user = await self.users.get(record.user_id)
        if user is None:
            raise AuthenticationError("Invalid or expired verification link.")

        user.email_verified_at = user.email_verified_at or now
        record.used_at = now
        await self.session.flush()
        return user
