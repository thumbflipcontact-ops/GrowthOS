"""End-to-end FastAPI tests — app startup (incl. plugin catalog discovery), auth, and
project CRUD through real HTTP calls. See docs/api/API_DESIGN.md.

`get_db` is overridden to use the same transactional `db_session` fixture every other
integration test uses, so API-driven writes roll back at teardown exactly like everything
else — the app's own `lifespan` still runs for real (its own engine, real plugin catalog
sync), only the per-request session is redirected.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


class _FakeArqRedis:
    """A minimal stand-in with a working `ping()` — real enough for /health's redis check
    (see test_health.py for dedicated healthy/degraded coverage) without requiring a real
    Redis in every test that merely boots the app."""

    async def ping(self) -> bool:
        return True


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_arq_redis, get_db
    from app.main import app

    async def override_get_db():
        yield db_session

    async def override_get_arq_redis():
        return _FakeArqRedis()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_arq_redis] = override_get_arq_redis
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health(api_client: AsyncClient) -> None:
    r = await api_client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.asyncio
async def test_plugin_catalog_reflects_discovered_plugins_but_requires_auth(
    api_client: AsyncClient,
) -> None:
    r = await api_client.get("/api/v1/plugins/catalog")
    assert r.status_code == 401  # not authenticated yet


@pytest.mark.asyncio
async def test_register_login_me_logout_flow(api_client: AsyncClient) -> None:
    register = await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-api-flow",
            "email": "founder@example.com",
            "name": "Founder",
            "password": "correct-horse-battery-staple",
        },
    )
    assert register.status_code == 201
    user_id = register.json()["id"]
    assert "growthos_session" in api_client.cookies

    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == user_id

    logout = await api_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    me_after_logout = await api_client.get("/api/v1/auth/me")
    assert me_after_logout.status_code == 401

    login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200
    assert login.json()["id"] == user_id


def _parse_set_cookie_attrs(set_cookie_header: str) -> dict[str, str | None]:
    attrs: dict[str, str | None] = {}
    for part in set_cookie_header.split(";")[1:]:
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            attrs[key.strip().lower()] = value.strip().lower()
        else:
            attrs[part.lower()] = None
    return attrs


@pytest.mark.asyncio
async def test_logout_clears_cookies_with_the_same_secure_and_samesite_login_set(
    api_client: AsyncClient,
) -> None:
    """A delete_cookie() whose secure/samesite attributes don't match the original set_cookie()
    produces a Set-Cookie header real browsers silently drop in a cross-site deployment (Vercel
    frontend + Railway backend) — the session cookie never actually gets cleared, so the user
    stays logged in even though /logout returned 204 and the frontend redirected to /login. This
    exact bug shipped once already (see app/api/v1/auth.py's _cookie_security_attrs docstring).
    Asserting structural parity between login's and logout's Set-Cookie headers — rather than
    hardcoding secure=True/False for one environment — is what would have caught it: the bug is
    invisible under ENVIRONMENT=local (both sides happen to default to secure=False;
    samesite=lax), so a test pinned to local's values would pass regardless of this mismatch.
    """
    register = await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-logout-cookie-parity",
            "email": "cookie-parity@example.com",
            "name": "Founder",
            "password": "correct-horse-battery-staple",
        },
    )
    assert register.status_code == 201
    set_cookie_headers = register.headers.get_list("set-cookie")
    session_set = next(h for h in set_cookie_headers if h.startswith("growthos_session="))
    csrf_set = next(h for h in set_cookie_headers if h.startswith("growthos_csrf="))
    session_set_attrs = _parse_set_cookie_attrs(session_set)
    csrf_set_attrs = _parse_set_cookie_attrs(csrf_set)

    logout = await api_client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    clear_cookie_headers = logout.headers.get_list("set-cookie")
    session_clear = next(h for h in clear_cookie_headers if h.startswith("growthos_session="))
    csrf_clear = next(h for h in clear_cookie_headers if h.startswith("growthos_csrf="))
    session_clear_attrs = _parse_set_cookie_attrs(session_clear)
    csrf_clear_attrs = _parse_set_cookie_attrs(csrf_clear)

    for attr in ("secure", "samesite"):
        assert (attr in session_clear_attrs) == (attr in session_set_attrs), attr
        assert session_clear_attrs.get(attr) == session_set_attrs.get(attr), attr
        assert (attr in csrf_clear_attrs) == (attr in csrf_set_attrs), attr
        assert csrf_clear_attrs.get(attr) == csrf_set_attrs.get(attr), attr


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(api_client: AsyncClient) -> None:
    payload = {
        "org_name": "Acme",
        "org_slug": "acme-dup-1",
        "email": "dup@example.com",
        "name": "Founder",
        "password": "correct-horse-battery-staple",
    }
    first = await api_client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    payload["org_slug"] = "acme-dup-2"
    second = await api_client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-wrongpw",
            "email": "wrongpw@example.com",
            "name": "Founder",
            "password": "correct-horse-battery-staple",
        },
    )
    r = await api_client.post(
        "/api/v1/auth/login", json={"email": "wrongpw@example.com", "password": "not-it"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "authentication_error"


@pytest.mark.asyncio
async def test_project_crud_and_org_scoped_authorization(
    api_client: AsyncClient, db_session
) -> None:
    import uuid

    from app.repositories.organization_repository import OrganizationRepository

    register = await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-project-crud",
            "email": "projowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    assert register.status_code == 201

    # Registration writes through the same overridden db_session the API uses (see
    # api_client's fixture), so it's visible here without a separate query round-trip to a
    # different connection.
    org = await OrganizationRepository(db_session).get_by_slug("acme-project-crud")
    assert org is not None
    org_id = org.id

    create = await api_client.post(
        f"/api/v1/orgs/{org_id}/projects", json={"name": "ScoutSEO", "slug": "scoutseo-crud"}
    )
    assert create.status_code == 201
    project_id = create.json()["id"]
    assert create.json()["icp_config"] == {}
    assert create.json()["status"] == "active"

    listed = await api_client.get(f"/api/v1/orgs/{org_id}/projects")
    assert listed.status_code == 200
    assert any(p["id"] == project_id for p in listed.json())

    fetched = await api_client.get(f"/api/v1/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["slug"] == "scoutseo-crud"

    other_org_id = uuid.uuid4()
    forbidden = await api_client.get(f"/api/v1/orgs/{other_org_id}/projects")
    assert forbidden.status_code in (403, 404)

    missing_project = await api_client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert missing_project.status_code == 404
