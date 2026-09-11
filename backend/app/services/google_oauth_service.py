""""Continue with Google" account login/signup — see app/api/v1/auth_oauth.py, the only
caller.

Distinct from OAuthConnectionService (app/services/oauth_connection.py): that service links
a *project* to a data-source/publishing plugin (Reddit) for an *already-authenticated* user
and requires `get_current_user`; this service establishes the session itself, so it can never
depend on one. Reuses the same low-level, provider-agnostic OAuthClient/OAuthProviderSpec
(app/core/oauth/client.py, plugins/_shared/oauth.py) the plugin framework uses — Google's own
endpoints are declared inline below rather than via a plugin manifest, since this isn't a
plugin. Uses Google's userinfo endpoint (one extra HTTPS call) rather than local ID-token JWT
signature verification — simpler, no JWKS/crypto dependency, and Google's userinfo response
is exactly what the plugin OAuth framework already trusts an access token to fetch.

Its own minimal signed state token (not app/core/oauth/state.py's OAuthState) — that one
carries `project_id`/`plugin_key`/`label`/`user_id`, all meaningless before a session exists;
login only needs CSRF protection, nothing to correlate back to.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from plugins._shared.oauth import OAuthProviderSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.oauth.client import OAuthClient
from app.core.oauth.errors import OAuthClientNotConfigured, TokenExchangeFailed
from app.models.audit import AuditLog
from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.oauth_identity import OAuthIdentity
from app.repositories.oauth_identity_repository import OAuthIdentityRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository

_GOOGLE_SPEC = OAuthProviderSpec(
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=("openid", "email", "profile"),
    token_endpoint_auth_method="client_secret_post",
    # prompt=select_account: a returning user who's ever used Google for anything else on
    # this machine shouldn't get silently signed in as whichever Google account happens to
    # be currently active — always show the account picker.
    extra_authorize_params={"access_type": "online", "prompt": "select_account"},
)
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_HTTP_TIMEOUT_SECONDS = 10.0
_STATE_SALT = "growthos-google-login-state"
_STATE_MAX_AGE_SECONDS = 600  # 10 minutes — same window app/core/oauth/state.py's own uses.

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_INVALID_RE.sub("-", value.lower().strip()).strip("-")
    return (slug or "workspace")[:90]


def _state_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=_STATE_SALT)


def create_login_state_token(*, secret_key: str) -> str:
    return _state_serializer(secret_key).dumps({"nonce": secrets.token_urlsafe(16)})


def verify_login_state_token(token: str, *, secret_key: str) -> bool:
    """True if the signature is valid and unexpired — never raises, same "invalid is just
    false, not a 500" contract as verify_session_token/verify_state_token."""
    try:
        _state_serializer(secret_key).loads(token, max_age=_STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return True


def build_google_authorize_url(settings: Settings) -> str:
    """No database access needed — used directly by GET /auth/google/start, which never
    touches a session. Module-level rather than a GoogleOAuthService method for exactly that
    reason: nothing here is a call that legitimately needs `session=None`."""
    state_token = create_login_state_token(secret_key=settings.secret_key.get_secret_value())
    return _client(settings).build_authorize_url(_GOOGLE_SPEC, state=state_token)


class GoogleOAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.organizations = OrganizationRepository(session)
        self.identities = OAuthIdentityRepository(session)

    async def handle_callback(self, *, code: str, state_token: str) -> User:
        if not verify_login_state_token(
            state_token, secret_key=self.settings.secret_key.get_secret_value()
        ):
            raise AuthenticationError("Google sign-in link expired or is invalid — try again.")

        client = _client(self.settings)
        try:
            token = await client.exchange_code(_GOOGLE_SPEC, code=code)
        except TokenExchangeFailed as exc:
            raise AuthenticationError(f"Could not complete Google sign-in: {exc}") from exc

        profile = await self._fetch_userinfo(token.access_token)
        subject = profile.get("sub")
        email = profile.get("email")
        if not subject or not email:
            raise AuthenticationError("Google did not return a usable account profile.")
        if not profile.get("email_verified"):
            raise AuthenticationError("Google reports this email address is unverified.")
        name = profile.get("name") or email.split("@")[0]

        existing_identity = await self.identities.get_by_provider_and_subject("google", subject)
        if existing_identity is not None:
            user = await self.session.get(User, existing_identity.user_id)
            assert user is not None  # FK guarantees the referenced user still exists
            return await self._complete_login(user)

        user = await self.users.get_by_email(email)
        if user is not None:
            # An existing password (or other-provider) account with this exact,
            # Google-verified email — link Google as an additional way in rather than create
            # a duplicate account. Google's verification is a stronger signal than our own
            # unclicked verification email, so this also clears any outstanding
            # email_verified_at gap on the existing account.
            if user.email_verified_at is None:
                user.email_verified_at = datetime.now(UTC)
            self.session.add(
                OAuthIdentity(user_id=user.id, provider="google", provider_user_id=subject)
            )
            await self.session.flush()
            return await self._complete_login(user)

        return await self._create_user(email=email, name=name, google_subject=subject)

    async def _create_user(self, *, email: str, name: str, google_subject: str) -> User:
        organization = Organization(
            name=f"{name}'s Workspace", slug=f"{_slugify(name)}-{uuid.uuid4().hex[:8]}"
        )
        self.session.add(organization)
        await self.session.flush()

        # A Google signup issues a session exactly like a password signup/login does — counts
        # the same way for app/core/agent_lifecycle.py's 48h-inactivity check. No password to
        # hash (password_hash stays NULL — see app/models/identity.py's own note);
        # email_verified_at is set immediately since Google already verified this address,
        # skipping the separate "check your email" step entirely.
        user = User(
            email=email,
            name=name,
            password_hash=None,
            last_login_at=datetime.now(UTC),
            email_verified_at=datetime.now(UTC),
        )
        self.session.add(user)
        await self.session.flush()

        self.session.add(
            Membership(org_id=organization.id, user_id=user.id, role=MembershipRole.OWNER)
        )
        self.session.add(
            OAuthIdentity(user_id=user.id, provider="google", provider_user_id=google_subject)
        )
        self.session.add(
            AuditLog(
                org_id=organization.id,
                actor_user_id=user.id,
                action="user.registered_via_google",
                target=email,
            )
        )
        await self.session.flush()
        return user

    async def _complete_login(self, user: User) -> User:
        user.last_login_at = datetime.now(UTC)
        first_membership = (
            await self.session.execute(select(Membership).where(Membership.user_id == user.id))
        ).scalars().first()
        if first_membership is not None:
            self.session.add(
                AuditLog(
                    org_id=first_membership.org_id,
                    actor_user_id=user.id,
                    action="login.succeeded_via_google",
                    target=user.email,
                )
            )
        await self.session.flush()
        return user

    async def _fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as http_client:
                response = await http_client.get(
                    _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
                )
        except httpx.HTTPError as exc:
            raise AuthenticationError(
                f"Could not reach Google to read the account profile: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise AuthenticationError(
                f"Google rejected the account profile request ({response.status_code})."
            )
        body: Any = response.json()
        if not isinstance(body, dict):
            raise AuthenticationError("Google returned an unexpected account profile response.")
        return body


def _client(settings: Settings) -> OAuthClient:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    if not client_id or not client_secret:
        raise OAuthClientNotConfigured(
            "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must both be set in the "
            "environment to use Google sign-in."
        )
    return OAuthClient(
        client_id=client_id,
        client_secret=client_secret.get_secret_value(),
        redirect_uri=f"{settings.oauth_callback_base_url}/api/v1/auth/google/callback",
    )


__all__ = [
    "GoogleOAuthService",
    "build_google_authorize_url",
    "create_login_state_token",
    "verify_login_state_token",
]
