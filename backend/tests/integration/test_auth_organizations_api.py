"""Tests for GET /api/v1/auth/me/organizations — see app/api/v1/auth.py. The frontend needs
this right after register/login, since RegisterRequest's response (UserResponse) deliberately
carries no org data.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_organizations_returns_the_org_created_at_registration(
    api_client: AsyncClient,
) -> None:
    register = await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-me-orgs",
            "email": "owner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    assert register.status_code == 201

    r = await api_client.get("/api/v1/auth/me/organizations")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "Acme"
    assert body[0]["slug"] == "acme-me-orgs"
    assert "id" in body[0]


@pytest.mark.asyncio
async def test_me_organizations_requires_authentication(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/v1/auth/me/organizations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_organizations_is_empty_list_not_error_when_somehow_orgless(
    api_client: AsyncClient, db_session
) -> None:
    from app.core.security import hash_password
    from app.models.identity import User

    db_session.add(
        User(email="orphan@example.com", name="Orphan", password_hash=hash_password("x" * 12))
    )
    await db_session.flush()

    login = await api_client.post(
        "/api/v1/auth/login", json={"email": "orphan@example.com", "password": "x" * 12}
    )
    assert login.status_code == 200

    r = await api_client.get("/api/v1/auth/me/organizations")
    assert r.status_code == 200
    assert r.json() == []
