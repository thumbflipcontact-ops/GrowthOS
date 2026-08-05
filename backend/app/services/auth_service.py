"""Authentication scaffold — see docs/auth/AUTHENTICATION.md.

`register` is the public signup flow (Phase 4 — docs/billing/BILLING_ARCHITECTURE.md,
docs/decisions/0001-multi-tenancy.md): anyone can create an organization + owner user. It
does not create a subscription — that happens separately via BillingService's Checkout
Session (app/api/v1/billing.py), so a freshly registered org exists but is not yet entitled
to anything paid until checkout completes. Org invitations / roles beyond a single owner
remain deferred — a real gap for a team account, not yet needed for the single-owner-per-org
model this launch targets. Every login attempt, successful or not, writes an audit_log row
per docs/security/SECURITY.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ValidationError
from app.core.security import hash_password, verify_password
from app.models.audit import AuditLog
from app.models.identity import Membership, MembershipRole, Organization, User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.organizations = OrganizationRepository(session)

    async def register(
        self, *, org_name: str, org_slug: str, email: str, name: str, password: str
    ) -> User:
        if await self.users.get_by_email(email) is not None:
            raise ValidationError("A user with this email already exists.")
        if await self.organizations.get_by_slug(org_slug) is not None:
            raise ValidationError("An organization with this slug already exists.")

        organization = Organization(name=org_name, slug=org_slug)
        self.session.add(organization)
        await self.session.flush()

        user = User(email=email, name=name, password_hash=hash_password(password))
        self.session.add(user)
        await self.session.flush()

        membership = Membership(org_id=organization.id, user_id=user.id, role=MembershipRole.OWNER)
        self.session.add(membership)

        self.session.add(
            AuditLog(
                org_id=organization.id,
                actor_user_id=user.id,
                action="user.registered",
                target=email,
            )
        )
        await self.session.flush()
        return user

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            # Deliberately the same error for "no such user" and "wrong password" — do not
            # let a failed-login response reveal which one it was.
            await self._audit_login_attempt(
                org_id=None, actor_user_id=None, action="login.failed", target=email
            )
            raise AuthenticationError("Invalid email or password.")

        result = await self.session.execute(select(Membership).where(Membership.user_id == user.id))
        first_membership = result.scalars().first()
        org_id = first_membership.org_id if first_membership else None

        await self._audit_login_attempt(
            org_id=org_id, actor_user_id=user.id, action="login.succeeded", target=email
        )
        return user

    async def _audit_login_attempt(
        self, *, org_id: uuid.UUID | None, actor_user_id: uuid.UUID | None, action: str, target: str
    ) -> None:
        if org_id is None:
            # No org to attribute a failed login by an unknown email to — skip rather than
            # violate audit_log.org_id's NOT NULL constraint. A future multi-org login page
            # (Phase 4) would resolve org from a subdomain/selector before this point.
            return
        self.session.add(
            AuditLog(org_id=org_id, actor_user_id=actor_user_id, action=action, target=target)
        )
        await self.session.flush()
