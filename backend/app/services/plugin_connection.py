"""Creates and lists a project's plugin connections. See docs/plugins/PLUGIN_ARCHITECTURE.md
§"Plugin-declared configuration and the generic connection UI" and docs/api/API_DESIGN.md.

This is the piece the Platform Readiness Review (docs/reviews/PLATFORM_READINESS_REVIEW.md
§1) found missing: `GET /api/v1/plugins/catalog` existed, but nothing let a plugin developer
(or the frontend's DynamicConnectionForm) actually connect a finished plugin to a project.
Config validation reuses the plugin's own `config_schema` (a pydantic model already held
in-process on the manifest) directly — no separate JSON Schema validator dependency needed,
since PluginManifest.config_schema is the pydantic class itself, not just its derived JSON
Schema.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.plugin_catalog import PluginCatalog
from app.models.audit import AuditLog
from app.models.plugin import PluginCapability, PluginConnection
from app.repositories.plugin_repository import PluginConnectionRepository


class PluginConnectionService:
    def __init__(self, session: AsyncSession, catalog: PluginCatalog) -> None:
        self.session = session
        self.catalog = catalog
        self.connections = PluginConnectionRepository(session)

    async def create(
        self,
        *,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plugin_key: str,
        config: dict,
        capabilities_enabled: list[str],
        label: str = "default",
    ) -> PluginConnection:
        manifest = self.catalog.get(plugin_key)
        if manifest is None:
            raise NotFoundError(
                f"No installed plugin with key {plugin_key!r}.",
                details={"plugin_key": plugin_key},
            )

        existing = await self.connections.get_by_project_plugin_and_label(
            project_id, plugin_key, label
        )
        if existing is not None:
            raise ValidationError(
                f"This project already has a connection for plugin {plugin_key!r} with "
                f"label {label!r}.",
                details={"plugin_key": plugin_key, "label": label},
            )

        unknown_capabilities = set(capabilities_enabled) - set(manifest.capabilities)
        if unknown_capabilities:
            raise ValidationError(
                f"Plugin {plugin_key!r} does not declare capabilities: "
                f"{sorted(unknown_capabilities)!r}.",
                details={"plugin_key": plugin_key, "unknown": sorted(unknown_capabilities)},
            )

        if manifest.config_schema is not None:
            try:
                manifest.config_schema.model_validate(config)
            except PydanticValidationError as exc:
                raise ValidationError(
                    f"Connection config does not match plugin {plugin_key!r}'s config_schema.",
                    details={"plugin_key": plugin_key, "errors": exc.errors()},
                ) from exc

        connection = PluginConnection(
            project_id=project_id,
            plugin_key=plugin_key,
            label=label,
            config=config,
            capabilities_enabled=[PluginCapability(c) for c in capabilities_enabled],
        )
        connection = await self.connections.add(connection)

        # See docs/auth/AUTHENTICATION.md §"Plugin credentials vs. user authentication":
        # "Connecting, disconnecting, or reconfiguring a plugin connection writes an
        # audit_log row."
        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="plugin_connection.created",
                target=plugin_key,
            )
        )
        await self.session.flush()
        return connection

    async def list_for_project(self, project_id: uuid.UUID) -> list[PluginConnection]:
        return await self.connections.list_by_project(project_id)
