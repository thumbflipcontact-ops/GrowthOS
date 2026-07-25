"""See app/core/agent_registry.py. Uses the real `conversation_finder` agent package
(pip installed editable, same convention as plugins/reddit and plugins/dummy in
plugins/_shared's tests) so this proves the actual import-by-key convention works, not just
an injectable stub.
"""

from __future__ import annotations

import pytest
from app.core.agent_registry import load_agent
from app.core.errors import NotFoundError


def test_loads_the_real_conversation_finder_agent() -> None:
    agent = load_agent("conversation_finder")
    assert agent.key == "conversation_finder"
    assert callable(agent.run)


def test_raises_not_found_for_an_unknown_agent_key() -> None:
    with pytest.raises(NotFoundError):
        load_agent("not-a-real-agent")


def test_raises_not_found_when_the_module_has_no_agent_singleton(monkeypatch) -> None:
    import sys
    import types

    parent_pkg = types.ModuleType("agents.no_agent_singleton")
    parent_pkg.__path__ = []  # marks it as a package so the dotted import resolves
    fake_module = types.ModuleType("agents.no_agent_singleton.agent")
    monkeypatch.setitem(sys.modules, "agents.no_agent_singleton", parent_pkg)
    monkeypatch.setitem(sys.modules, "agents.no_agent_singleton.agent", fake_module)

    with pytest.raises(NotFoundError):
        load_agent("no_agent_singleton")
