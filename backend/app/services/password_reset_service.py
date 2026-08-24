"""Forgot/reset password — see app/api/v1/auth.py's /auth/forgot-password and
/auth/reset-password routes (the only callers) and app/models/password_reset.py.

request_reset never reveals whether the email exists — same "identical response either way"
rule AuthService.authenticate() already applies to login, for the same reason (a different
response shape would let an attacker enumerate registered emails).
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
from app.core.email.templates import password_reset_requested
from app.core.errors import AuthenticationError
from app.core.security import hash_password
from app.models.identity import User
from app.models.password_reset import PasswordResetToken
from app.repositories.password_reset_repository import PasswordResetTokenRepository
from app.repositories.user_repository import UserRepository

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger()

_TOKEN_TTL = timedelta(hours=1)


class PasswordResetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = PasswordResetTokenRepository(session)

    async def request_reset(self, *, email: str) -> None:
        user = await self.users.get_by_email(email)
        if user is None:
            return

        full_token = secrets.token_urlsafe(32)
        record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_api_key(full_token),
            expires_at=datetime.now(UTC) + _TOKEN_TTL,
        )
        await self.tokens.add(record)

        reset_url = f"{self.settings.frontend_origin}/reset-password?token={full_token}"
        subject, html_body = password_reset_requested(user_name=user.name, reset_url=reset_url)

        try:
            client = ResendClient.from_settings(self.settings)
        except EmailNotConfigured:
            logger.warning("password_reset.email_not_configured", user_id=str(user.id))
            return
        try:
            await client.send(to=user.email, subject=subject, html_body=html_body)
        except EmailError as exc:
            # The token is already persisted regardless — a delivery failure here shouldn't
            # be distinguishable from "email doesn't exist" in the response either way.
            logger.warning(
                "password_reset.email_send_failed", user_id=str(user.id), error=str(exc)
            )

    async def reset_password(self, *, token: str, new_password: str) -> User:
        record = await self.tokens.get_by_hash(hash_api_key(token))
        now = datetime.now(UTC)
        if record is None or record.used_at is not None or record.expires_at < now:
            raise AuthenticationError("Invalid or expired reset link.")

        user = await self.users.get(record.user_id)
        if user is None:
            raise AuthenticationError("Invalid or expired reset link.")

        user.password_hash = hash_password(new_password)
        record.used_at = now
        await self.session.flush()
        return user
