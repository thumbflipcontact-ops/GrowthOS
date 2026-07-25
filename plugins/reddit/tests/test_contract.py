"""Runs the shared plugin contract test suite against the real Reddit plugin — see
plugins/_shared/tests/test_plugin_contract.py and CONTRIBUTING.md "Adding a new plugin".
This proves RedditPlugin structurally honors its own manifest (implements Searchable +
Publishable, has a real OAuthProviderSpec, health_check() returns a bool) — it does not and
cannot verify search()/publish() work against the real Reddit API; see test_client.py and
test_plugin.py for that, against a mocked transport.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from plugins._shared.base import ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.tests.test_plugin_contract import assert_plugin_contract
from plugins.reddit.plugin import create_plugin

_FAKE_CONNECTION = ResolvedConnection(
    project_id=uuid.uuid4(),
    plugin_key="reddit",
    label="default",
    config={"subreddits": ["SEO"]},
    credentials=OAuth2Credentials(
        access_token="fake-access-token",
        refresh_token="fake-refresh-token",
        token_type="bearer",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=("read", "submit", "identity"),
    ),
)


def test_reddit_plugin_satisfies_contract_without_network(monkeypatch) -> None:
    # assert_plugin_contract calls health_check(), which normally makes a real network call
    # (GET /api/v1/me) — redirected here to a fake success so this test is safe and
    # deterministic without ever touching the network. See test_plugin.py for behavior
    # coverage of health_check() itself, including the failure path.
    import plugins.reddit.client as client_module

    async def fake_me(self) -> dict:
        return {"name": "growthos-bot"}

    monkeypatch.setattr(client_module.RedditClient, "me", fake_me)

    plugin = create_plugin(connection=_FAKE_CONNECTION)
    assert plugin.manifest.key == "reddit"
    assert plugin.manifest.auth_type == "oauth2"
    assert plugin.manifest.oauth is not None
    assert_plugin_contract(plugin)
