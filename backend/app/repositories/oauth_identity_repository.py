from __future__ import annotations

from sqlalchemy import select

from app.models.oauth_identity import OAuthIdentity
from app.repositories.base import Repository


class OAuthIdentityRepository(Repository[OAuthIdentity]):
    model = OAuthIdentity

    async def get_by_provider_and_subject(
        self, provider: str, provider_user_id: str
    ) -> OAuthIdentity | None:
        """Matches `oauth_identities`' `unique(provider, provider_user_id)` constraint — how
        a returning Google login is matched back to its account."""
        result = await self.session.execute(
            select(OAuthIdentity).where(
                OAuthIdentity.provider == provider,
                OAuthIdentity.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()
