"""Runs the shared plugin contract test suite against the real Twitter/X plugin — see
plugins/_shared/tests/test_plugin_contract.py and CONTRIBUTING.md "Adding a new plugin".
This proves TwitterPlugin structurally honors its own manifest (implements Searchable +
Publishable, has a real OAuthProviderSpec, health_check() returns a bool) — it does not and
cannot verify search()/publish() work against the real X API; see test_client.py and
test_plugin.py for that, against a mocked transport.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from plugins._shared.base import ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.tests.test_plugin_contract import assert_plugin_contract
from plugins.twitter.plugin import create_plugin

_FAKE_CONNECTION = ResolvedConnection(
    project_id=uuid.uuid4(),
    plugin_key="twitter",
    label="default",
    config={},
    credentials=OAuth2Credentials(
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_type="bearer",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=("tweet.read", "tweet.write", "users.read", "offline.access"),
    ),
)


def test_twitter_plugin_satisfies_contract_without_network(monkeypatch) -> None:
    # assert_plugin_contract calls health_check(), which normally makes a real network call
    # (GET /2/users/me) — redirected here to a fake success so this test is safe and
    # deterministic without ever touching the network. See test_plugin.py for behavior
    # coverage of health_check() itself, including the failure path.
    import plugins.twitter.client as client_module

    async def fake_me(self) -> dict:
        return {"data": {"id": "1", "username": "growthos_bot"}}

    monkeypatch.setattr(client_module.TwitterClient, "me", fake_me)

    plugin = create_plugin(connection=_FAKE_CONNECTION)
    assert plugin.manifest.key == "twitter"
    assert plugin.manifest.auth_type == "oauth2"
    assert plugin.manifest.oauth is not None
    assert plugin.manifest.oauth.pkce == "required"
    assert_plugin_contract(plugin)
