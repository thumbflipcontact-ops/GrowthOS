"""Runs the shared plugin contract test suite against the real LinkedIn plugin — see
plugins/_shared/tests/test_plugin_contract.py and CONTRIBUTING.md "Adding a new plugin".
This proves LinkedInPlugin structurally honors its own manifest (implements Publishable
only — no Searchable, see README §"Why no search()" — has a real OAuthProviderSpec,
health_check() returns a bool) — it does not and cannot verify publish() works against the
real LinkedIn API; see test_client.py and test_plugin.py for that, against a mocked
transport.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from plugins._shared.base import ResolvedConnection, Searchable
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.tests.test_plugin_contract import assert_plugin_contract
from plugins.linkedin.plugin import create_plugin

_FAKE_CONNECTION = ResolvedConnection(
    project_id=uuid.uuid4(),
    plugin_key="linkedin",
    label="default",
    config={},
    credentials=OAuth2Credentials(
        access_token="fake-access-token",
        refresh_token=None,  # LinkedIn does not guarantee a refresh_token — see README
        token_type="bearer",
        expires_at=datetime.now(UTC) + timedelta(days=60),
        granted_scopes=("openid", "profile", "w_member_social"),
    ),
)


def test_linkedin_plugin_satisfies_contract_without_network(monkeypatch) -> None:
    # assert_plugin_contract calls health_check(), which normally makes a real network call
    # (GET /v2/userinfo) — redirected here to a fake success so this test is safe and
    # deterministic without ever touching the network. See test_plugin.py for behavior
    # coverage of health_check() itself, including the failure path.
    import plugins.linkedin.client as client_module

    async def fake_userinfo(self) -> dict:
        return {"sub": "abc123", "name": "Founder"}

    monkeypatch.setattr(client_module.LinkedInClient, "userinfo", fake_userinfo)

    plugin = create_plugin(connection=_FAKE_CONNECTION)
    assert plugin.manifest.key == "linkedin"
    assert plugin.manifest.auth_type == "oauth2"
    assert plugin.manifest.oauth is not None
    assert plugin.manifest.capabilities == ("publishable",)
    assert not isinstance(plugin, Searchable)
    assert_plugin_contract(plugin)
