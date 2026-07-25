"""Phase 1 test fixture — see README.md. Not a real plugin."""

from __future__ import annotations

from plugins._shared.base import PluginQuery, PluginResult
from plugins.dummy.manifest import MANIFEST


class DummyPlugin:
    manifest = MANIFEST

    def __init__(self, connection: object) -> None:
        self._connection = connection

    async def search(self, query: PluginQuery) -> list[PluginResult]:
        return [
            PluginResult(
                url="https://example.invalid/dummy",
                title="dummy result",
                body=f"searched for: {', '.join(query.terms)}",
                author=None,
            )
        ]

    async def health_check(self) -> bool:
        return True


def create_plugin(connection: object) -> DummyPlugin:
    return DummyPlugin(connection)
