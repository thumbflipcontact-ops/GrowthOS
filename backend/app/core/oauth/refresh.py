"""The OAuth token-refresh sweep's core logic — see docs/auth/OAUTH2_ARCHITECTURE.md §5.2,
§6 and ARCHITECTURE.md §7 (background workers). Deliberately separated from
app/jobs/oauth_refresh.py's Arq periodic-job wrapper — the same pattern as
app/core/dispatcher.py/app/jobs/events.py — so this runs and is tested as plain async/await
against a real session, without a running Arq worker or a real Redis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import derive_master_key, envelope_decrypt, envelope_encrypt
from app.core.oauth.client import OAuthClient
from app.core.oauth.errors import (
    OAuthClientNotConfigured,
    PermanentRefreshFailure,
    TokenExchangeFailed,
)
from app.core.plugin_catalog import PluginCatalog
from app.models.audit import AuditLog
from app.models.plugin import PluginConnection, PluginConnectionStatus
from app.models.project import Project

logger = structlog.get_logger()

# Refresh a token this far ahead of its actual expiry — generous margin against the sweep's
# own poll interval plus a slow provider round trip, so a connection is essentially never
# actually seen expired by a plugin construction attempt (app/core/plugin_registry.py).
REFRESH_WINDOW = timedelta(minutes=10)


class OAuthRefreshSweep:
    def __init__(self, session: AsyncSession, catalog: PluginCatalog, settings: Settings) -> None:
        self.session = session
        self.catalog = catalog
        self.settings = settings

    async def run(self, *, now: datetime | None = None) -> int:
        """Refreshes every `connected` OAuth connection whose token expires within
        `REFRESH_WINDOW`. Returns the count processed (attempted, whether or not each
        individual refresh succeeded). Locks candidate rows with `FOR UPDATE SKIP LOCKED` —
        if a concurrent sweep run or a user-triggered reconnect
        (`OAuthConnectionService.handle_callback`) already holds a row's lock, this run simply
        skips it rather than blocking or double-processing it; the row waiting under a
        reconnect's own transaction will simply have a fresh `token_expires_at` by the next
        sweep cycle regardless."""
        now = now or datetime.now(UTC)
        cutoff = now + REFRESH_WINDOW

        result = await self.session.execute(
            select(PluginConnection)
            .where(
                PluginConnection.status == PluginConnectionStatus.CONNECTED,
                PluginConnection.token_expires_at.is_not(None),
                PluginConnection.token_expires_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        connections = list(result.scalars().all())

        for connection in connections:
            await self._refresh_one(connection, now=now)
        await self.session.commit()
        return len(connections)

    async def _refresh_one(self, connection: PluginConnection, *, now: datetime) -> None:
        manifest = self.catalog.get(connection.plugin_key)
        if manifest is None or manifest.oauth is None:
            logger.warning("oauth_refresh.unknown_plugin", plugin_key=connection.plugin_key)
            return

        master_key = derive_master_key(self.settings.credential_master_key.get_secret_value())
        assert connection.credentials_encrypted is not None
        assert connection.credential_data_key_wrapped is not None
        plaintext = envelope_decrypt(
            master_key, connection.credentials_encrypted, connection.credential_data_key_wrapped
        )
        stored = json.loads(plaintext)
        refresh_token = stored.get("refresh_token")
        if not refresh_token:
            logger.warning(
                "oauth_refresh.no_refresh_token",
                plugin_key=connection.plugin_key,
                connection_id=str(connection.id),
            )
            await self._mark_expired(connection)
            return

        try:
            client_id, client_secret = self.settings.oauth_client_credentials(connection.plugin_key)
        except OAuthClientNotConfigured:
            logger.error("oauth_refresh.client_not_configured", plugin_key=connection.plugin_key)
            return  # operator misconfiguration — leave CONNECTED, not the connection's fault

        client = OAuthClient(
            client_id=client_id.get_secret_value(),
            client_secret=client_secret.get_secret_value(),
            redirect_uri=(
                f"{self.settings.oauth_callback_base_url}/api/v1/oauth/{connection.plugin_key}/callback"
            ),
        )

        try:
            token = await client.refresh(manifest.oauth, refresh_token=refresh_token)
        except PermanentRefreshFailure:
            logger.warning(
                "oauth_refresh.permanently_failed",
                plugin_key=connection.plugin_key,
                connection_id=str(connection.id),
            )
            await self._mark_expired(connection)
            return
        except TokenExchangeFailed:
            # Transient — network error, provider 5xx, etc. Leave status=CONNECTED and
            # token_expires_at unchanged; the next sweep cycle retries automatically.
            logger.warning(
                "oauth_refresh.transient_failure",
                plugin_key=connection.plugin_key,
                connection_id=str(connection.id),
                exc_info=True,
            )
            return

        # A provider that doesn't rotate refresh tokens omits refresh_token from a refresh
        # response — keep using the existing one rather than overwriting it with None.
        new_payload = json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token or refresh_token,
                "token_type": token.token_type,
            }
        ).encode("utf-8")
        ciphertext, wrapped_data_key = envelope_encrypt(master_key, new_payload)

        connection.credentials_encrypted = ciphertext
        connection.credential_data_key_wrapped = wrapped_data_key
        connection.token_expires_at = token.expires_at
        connection.granted_scopes = list(token.granted_scopes)

    async def _mark_expired(self, connection: PluginConnection) -> None:
        connection.status = PluginConnectionStatus.EXPIRED
        project = await self.session.get(Project, connection.project_id)
        if project is not None:
            self.session.add(
                AuditLog(
                    org_id=project.org_id,
                    actor_user_id=None,
                    action="plugin_connection.oauth_expired",
                    target=connection.plugin_key,
                )
            )


__all__ = ["REFRESH_WINDOW", "OAuthRefreshSweep"]
