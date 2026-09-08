"""AppSumo-style lifetime-deal code redemption — see app/models/ltd_code.py and
docs/billing/BILLING_ARCHITECTURE.md.

Deliberately a separate flow from AuthService.register(), not that method with an optional
ltd_code param — redemption has genuinely different concerns (validating and consuming a
code, stamping the new org as is_ltd/max_projects=1) layered on the same org+user+membership
creation, and keeping them apart means a change to one can never silently affect the other's
much larger, unrelated caller base. The org+user+membership shape below is intentionally the
same as register()'s, not shared code — see that method's own docstring for why a little
duplication here is the right tradeoff.

Redeeming does not sign the caller in — same as a normal signup, the account still has to
verify its email (app/api/v1/ltd.py's route calls EmailVerificationService.send_verification_email
right after this, exactly like /auth/register does).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.ltd_code import LtdCodeStatus
from app.repositories.ltd_code_repository import LtdCodeRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository

# Every LTD org starts at exactly 1 — see Organization.max_projects's docstring and the
# "Option A" pricing decision this was built for: a single tier, single project, until a real
# multi-project UI exists to make a higher tier actually deliverable.
_LTD_MAX_PROJECTS = 1


class LtdRedemptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.codes = LtdCodeRepository(session)
        self.users = UserRepository(session)
        self.organizations = OrganizationRepository(session)

    async def redeem(
        self,
        *,
        code: str,
        org_name: str,
        org_slug: str,
        email: str,
        name: str,
        password: str,
    ) -> User:
        ltd_code = await self.codes.get_by_code(code)
        if ltd_code is None or ltd_code.status != LtdCodeStatus.UNREDEEMED:
            # Same message either way — a wrong code and an already-redeemed one look
            # identical to the caller, so this can't be used to enumerate which codes exist.
            raise ValidationError("This code is invalid or has already been redeemed.")
        if await self.users.get_by_email(email) is not None:
            raise ValidationError("A user with this email already exists.")
        if await self.organizations.get_by_slug(org_slug) is not None:
            raise ValidationError("An organization with this slug already exists.")

        organization = Organization(
            name=org_name, slug=org_slug, is_ltd=True, max_projects=_LTD_MAX_PROJECTS
        )
        self.session.add(organization)
        await self.session.flush()

        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password),
            last_login_at=datetime.now(UTC),
        )
        self.session.add(user)
        await self.session.flush()

        membership = Membership(org_id=organization.id, user_id=user.id, role=MembershipRole.OWNER)
        self.session.add(membership)

        ltd_code.status = LtdCodeStatus.REDEEMED
        ltd_code.redeemed_by_org_id = organization.id
        ltd_code.redeemed_at = datetime.now(UTC)

        self.session.add(
            AuditLog(
                org_id=organization.id,
                actor_user_id=user.id,
                action="ltd_code.redeemed",
                target=code,
            )
        )
        await self.session.flush()
        return user
