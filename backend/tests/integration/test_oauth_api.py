"""End-to-end proof of the OAuth2 API — start → callback → connected, disconnect, and the
failure paths (tampered state, unauthenticated callback) — see
docs/auth/OAUTH2_ARCHITECTURE.md §3, §5.1, §5.4.

Injects a fake OAuth-capable plugin manifest via the get_plugin_catalog dependency override
(no real installed OAuth plugin package exists yet — Reddit is explicitly out of scope) and
mocks the provider's token/revoke endpoints via httpx.MockTransport, the same techniques
already used in test_oauth_client.py and test_oauth_connection_service.py.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec

pytestmark = pytest.mark.integration

SPEC = OAuthProviderSpec(
    authorize_url="https://provider.invalid/authorize",
    token_url="https://provider.invalid/token",
    revoke_url="https://provider.invalid/revoke",
    scopes=("read",),
)

OAUTH_MANIFEST = PluginManifest(
    key="testoauth",
    interface_version="1.0",
    capabilities=("searchable",),
    auth_type="oauth2",
    oauth=SPEC,
)


def _success_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/revoke":
        return httpx.Response(200)
    return httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "read",
        },
    )


@pytest.fixture(autouse=True)
def _oauth_client_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TESTOAUTH_OAUTH_CLIENT_SECRET", "csecret")


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch: pytest.MonkeyPatch):
    import app.core.oauth.client as client_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_success_handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", fake_async_client)


@pytest_asyncio.fixture
async def api_client(db_session, _migrated_db):
    from app.api.deps import get_db, get_plugin_catalog
    from app.core.plugin_catalog import PluginCatalog, discover_installed_plugins
    from app.main import app

    async def override_get_db():
        yield db_session

    def override_get_plugin_catalog():
        catalog = PluginCatalog()
        catalog.refresh([*discover_installed_plugins(), OAUTH_MANIFEST])
        return catalog

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_plugin_catalog] = override_get_plugin_catalog
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test", follow_redirects=False
            ) as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def project_id(api_client: AsyncClient, db_session) -> str:
    from app.repositories.organization_repository import OrganizationRepository

    await api_client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Acme",
            "org_slug": "acme-oauth-api",
            "email": "oauthowner@example.com",
            "name": "Owner",
            "password": "correct-horse-battery-staple",
        },
    )
    org = await OrganizationRepository(db_session).get_by_slug("acme-oauth-api")
    assert org is not None

    create = await api_client.post(
        f"/api/v1/orgs/{org.id}/projects", json={"name": "ScoutSEO", "slug": "scoutseo-oauth-api"}
    )
    assert create.status_code == 201
    return create.json()["id"]


def _extract_state(authorize_url: str) -> str:
    params = parse_qs(urlparse(authorize_url).query)
    return params["state"][0]


@pytest.mark.asyncio
async def test_start_returns_an_authorize_url(api_client: AsyncClient, project_id: str) -> None:
    r = await api_client.post(f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start")
    assert r.status_code == 200
    assert r.json()["authorize_url"].startswith(SPEC.authorize_url)


@pytest.mark.asyncio
async def test_start_requires_authentication() -> None:
    from app.main import app as unauthenticated_app

    async with AsyncClient(
        transport=ASGITransport(app=unauthenticated_app), base_url="http://test"
    ) as client:
        project_id = "00000000-0000-0000-0000-000000000000"
        r = await client.post(
            f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
        )
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_full_connect_flow(api_client: AsyncClient, project_id: str) -> None:
    start = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    assert start.status_code == 200
    state = _extract_state(start.json()["authorize_url"])

    callback = await api_client.get(f"/api/v1/oauth/testoauth/callback?code=the-code&state={state}")
    assert callback.status_code == 302
    location = callback.headers["location"]
    assert "connected=testoauth" in location

    listed = await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")
    assert listed.status_code == 200
    connections = listed.json()
    assert len(connections) == 1
    assert connections[0]["plugin_key"] == "testoauth"
    assert connections[0]["status"] == "connected"
    assert connections[0]["granted_scopes"] == ["read"]
    assert connections[0]["token_expires_at"] is not None


@pytest.mark.asyncio
async def test_callback_rejects_tampered_state(api_client: AsyncClient, project_id: str) -> None:
    start = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    state = _extract_state(start.json()["authorize_url"])
    tampered = state[:-1] + ("A" if state[-1] != "A" else "B")

    callback = await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c&state={tampered}")
    assert callback.status_code == 302
    assert "error=authentication_error" in callback.headers["location"]

    listed = await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")
    assert listed.json() == []  # nothing was created


@pytest.mark.asyncio
async def test_callback_requires_authentication(api_client: AsyncClient, project_id: str) -> None:
    start = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    state = _extract_state(start.json()["authorize_url"])

    await api_client.post("/api/v1/auth/logout")
    callback = await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c&state={state}")
    assert callback.status_code == 401  # not a redirect — no legitimate session to redirect on
    assert callback.json()["error"]["code"] == "authentication_error"


@pytest.mark.asyncio
async def test_reconnect_updates_the_same_connection(api_client: AsyncClient, project_id: str) -> None:
    start1 = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    state1 = _extract_state(start1.json()["authorize_url"])
    await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c1&state={state1}")

    first_list = await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")
    first_id = first_list.json()[0]["id"]

    start2 = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    state2 = _extract_state(start2.json()["authorize_url"])
    await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c2&state={state2}")

    second_list = await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")
    assert len(second_list.json()) == 1  # still one connection, not two
    assert second_list.json()[0]["id"] == first_id


@pytest.mark.asyncio
async def test_disconnect_clears_the_connection(api_client: AsyncClient, project_id: str) -> None:
    start = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start"
    )
    state = _extract_state(start.json()["authorize_url"])
    await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c&state={state}")

    connections = (await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")).json()
    connection_id = connections[0]["id"]

    disconnect = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/{connection_id}/oauth/disconnect"
    )
    assert disconnect.status_code == 204

    after = (await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")).json()
    assert after[0]["status"] == "disconnected"
    assert after[0]["token_expires_at"] is None
    assert after[0]["granted_scopes"] == []


@pytest.mark.asyncio
async def test_disconnect_rejects_a_connection_from_another_project(
    api_client: AsyncClient, project_id: str
) -> None:
    import uuid

    r = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/{uuid.uuid4()}/oauth/disconnect"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_multiple_labels_produce_separate_connections(
    api_client: AsyncClient, project_id: str
) -> None:
    start1 = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start",
        json={"label": "default"},
    )
    state1 = _extract_state(start1.json()["authorize_url"])
    await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c1&state={state1}")

    start2 = await api_client.post(
        f"/api/v1/projects/{project_id}/plugin-connections/testoauth/oauth/start",
        json={"label": "second-account"},
    )
    state2 = _extract_state(start2.json()["authorize_url"])
    await api_client.get(f"/api/v1/oauth/testoauth/callback?code=c2&state={state2}")

    connections = (await api_client.get(f"/api/v1/projects/{project_id}/plugin-connections")).json()
    assert len(connections) == 2
    assert {c["label"] for c in connections} == {"default", "second-account"}
