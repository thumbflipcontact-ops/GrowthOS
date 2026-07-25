"""Loads a specific agent implementation by key, for execution. See
docs/agents/AGENT_ARCHITECTURE.md.

The dispatch-side counterpart to app/core/subscriptions.py's discovery-side
`discover_agent_subscriptions()` scan: that module answers "what agents are installed and
what do they subscribe to"; this module answers "given a key I already have (from
agent_configs.agent_key), load the thing that actually runs." Mirrors
app/core/plugin_registry.py's `_load_plugin_instance`: a plain import-by-known-key
convention, not another entry-point scan, because the caller isn't discovering what's
installed — it already knows which agent it needs (the same asymmetry
plugin_registry.py's module docstring explains for plugins).

Convention: `agents.<agent_key>.agent` must expose a module-level `AGENT: Agent` singleton —
plain, not constructed per call, because unlike a plugin (which needs per-connection
credentials resolved from `ResolvedConnection`), an agent's only per-run input is the
`AgentContext` it's handed at call time.
"""

from __future__ import annotations

import importlib
from typing import cast

from agents._shared.base import Agent

from app.core.errors import NotFoundError


def load_agent(agent_key: str) -> Agent:
    try:
        module = importlib.import_module(f"agents.{agent_key}.agent")
    except ImportError as exc:
        raise NotFoundError(
            f"No installed agent with key {agent_key!r}.", details={"agent_key": agent_key}
        ) from exc

    agent = getattr(module, "AGENT", None)
    if agent is None or not callable(getattr(agent, "run", None)):
        raise NotFoundError(
            f"agents.{agent_key}.agent must expose an AGENT singleton implementing run().",
            details={"agent_key": agent_key},
        )
    # `Agent` isn't @runtime_checkable (see agents/_shared/base.py), so this is a duck-typed
    # check (above), not an isinstance narrowing — the cast documents that mypy can't verify
    # any further than the runtime check already did.
    return cast(Agent, agent)
