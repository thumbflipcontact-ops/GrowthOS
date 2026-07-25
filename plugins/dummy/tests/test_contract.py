"""Runs the shared plugin contract test suite against the dummy fixture plugin itself — see
plugins/_shared/tests/test_plugin_contract.py and CONTRIBUTING.md "Adding a new plugin" step
5. This is the thing that step told plugin authors to do, applied here to close the gap the
Platform Readiness Review found: the one working plugin example had no tests at all,
including not this one."""

from __future__ import annotations

import uuid

from plugins._shared.base import ResolvedConnection
from plugins._shared.credentials import ApiKeyCredentials
from plugins._shared.tests.test_plugin_contract import assert_plugin_contract
from plugins.dummy.plugin import create_plugin

_FAKE_CONNECTION = ResolvedConnection(
    project_id=uuid.uuid4(),
    plugin_key="dummy",
    label="default",
    config={"greeting": "hello"},
    credentials=ApiKeyCredentials(api_key="fake-key-for-tests"),
)


def test_dummy_plugin_honors_its_manifest() -> None:
    assert_plugin_contract(create_plugin(connection=_FAKE_CONNECTION))
