"""See app/repositories/ and docs/architecture/LOCKED_DECISIONS.md."""

from __future__ import annotations

import pytest

from app.models.identity import Membership, MembershipRole, Organization, User
from app.models.project import Project
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import MembershipRepository, UserRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_organization_repository_get_by_slug(db_session) -> None:
    repo = OrganizationRepository(db_session)
    await repo.add(Organization(name="Acme", slug="acme-repo-test"))

    found = await repo.get_by_slug("acme-repo-test")
    assert found is not None
    assert found.name == "Acme"
    assert await repo.get_by_slug("does-not-exist") is None


@pytest.mark.asyncio
async def test_user_repository_get_by_email(db_session) -> None:
    repo = UserRepository(db_session)
    await repo.add(User(email="a@example.com", name="A", password_hash="x"))

    assert (await repo.get_by_email("a@example.com")) is not None
    assert (await repo.get_by_email("nope@example.com")) is None


@pytest.mark.asyncio
async def test_project_repository_scoped_to_org(db_session) -> None:
    org_repo = OrganizationRepository(db_session)
    org_a = await org_repo.add(Organization(name="A", slug="org-a-repo"))
    org_b = await org_repo.add(Organization(name="B", slug="org-b-repo"))

    project_repo = ProjectRepository(db_session)
    await project_repo.add(Project(org_id=org_a.id, name="P1", slug="p1"))
    await project_repo.add(Project(org_id=org_b.id, name="P2", slug="p2"))

    org_a_projects = await project_repo.list_by_org(org_a.id)
    assert [p.slug for p in org_a_projects] == ["p1"]


@pytest.mark.asyncio
async def test_membership_repository_get_by_org_and_user(db_session) -> None:
    org = await OrganizationRepository(db_session).add(Organization(name="A", slug="org-mem"))
    user = await UserRepository(db_session).add(User(email="m@example.com", name="M", password_hash="x"))
    membership_repo = MembershipRepository(db_session)
    await membership_repo.add(Membership(org_id=org.id, user_id=user.id, role=MembershipRole.OWNER))

    found = await membership_repo.get_by_org_and_user(org.id, user.id)
    assert found is not None
    assert found.role == MembershipRole.OWNER

    other_user = await UserRepository(db_session).add(
        User(email="other@example.com", name="Other", password_hash="x")
    )
    assert await membership_repo.get_by_org_and_user(org.id, other_user.id) is None
