"""Orchestrates the OAuth2 connect/reconnect/disconnect flow — see
docs/auth/OAUTH2_ARCHITECTURE.md §1, §3 and ADR 0011.

`PluginConnectionService` (Platform Improvement pass) still owns generic, non-OAuth
connection create/list; this service owns everything OAuth-specific: building an authorize
URL, handling the provider's callback, and disconnecting (revoke + clear credentials).
Refreshing an about-to-expire token is a separate concern — see app/jobs/oauth_refresh.py —
deliberately never triggered from a user-facing request path (docs/auth/OAUTH2_ARCHITECTURE.md
§3: "No refresh endpoint exists").

Translates app/core/oauth's protocol-level exceptions (InvalidState, TokenExchangeFailed) into
app/core/errors's HTTP-mapped domain exceptions at this boundary — the same pattern
app/core/plugin_registry.py already uses for the plugin SDK's CapabilityNotSupported.
"""

from __future__ import annotations

import json
import uuid

from plugins._shared.manifest import PluginManifest
from plugins._shared.oauth import OAuthProviderSpec
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import derive_master_key, envelope_decrypt, envelope_encrypt
from app.core.errors import AuthenticationError, NotFoundError, PluginError, ValidationError
from app.core.oauth.client import OAuthClient, TokenResponse
from app.core.oauth.errors import TokenExchangeFailed
from app.core.oauth.pkce import code_challenge_from_verifier, generate_code_verifier
from app.core.oauth.state import OAuthState, create_state_token, generate_nonce, verify_state_token
from app.core.plugin_catalog import PluginCatalog
from app.models.audit import AuditLog
from app.models.plugin import PluginConnection, PluginConnectionStatus
from app.models.project import Project
from app.repositories.plugin_repository import PluginConnectionRepository


class OAuthConnectionService:
    def __init__(self, session: AsyncSession, catalog: PluginCatalog, settings: Settings) -> None:
        self.session = session
        self.catalog = catalog
        self.settings = settings
        self.connections = PluginConnectionRepository(session)

    def start(
        self, *, project_id: uuid.UUID, plugin_key: str, label: str, user_id: uuid.UUID
    ) -> str:
        """Returns the `authorize_url` the frontend should navigate the browser to. Doubles
        as reconnect: starting again for a `label` with an existing `expired`/`error`
        connection is indistinguishable from a first connect until `handle_callback` resolves
        it — see docs/auth/OAUTH2_ARCHITECTURE.md §3, §5.3."""
        _manifest, spec = self._oauth_manifest_and_spec(plugin_key)

        code_verifier: str | None = None
        code_challenge: str | None = None
        if spec.pkce in ("required", "supported"):
            code_verifier = generate_code_verifier()
            code_challenge = code_challenge_from_verifier(code_verifier)

        state = OAuthState(
            project_id=project_id,
            plugin_key=plugin_key,
            label=label,
            user_id=user_id,
            code_verifier=code_verifier,
            nonce=generate_nonce(),
        )
        state_token = create_state_token(state, secret_key=self._session_secret())

        client = self._client_for(plugin_key)
        return client.build_authorize_url(spec, state=state_token, code_challenge=code_challenge)

    async def handle_callback(
        self, *, code: str, state_token: str, current_user_id: uuid.UUID
    ) -> PluginConnection:
        """Verifies `state_token` (signature, age, and that its embedded `user_id` matches
        the currently authenticated session — see docs/auth/OAUTH2_ARCHITECTURE.md §6),
        exchanges `code` for tokens, envelope-encrypts them (ADR 0010), and upserts the
        `plugin_connections` row: creates it on a first connect, updates the same row in
        place on a reconnect (same id, `config`/`capabilities_enabled` preserved)."""
        state = verify_state_token(state_token, secret_key=self._session_secret())
        if state is None:
            raise AuthenticationError("OAuth state is missing, invalid, or expired.")
        if state.user_id != current_user_id:
            raise AuthenticationError("OAuth state does not match the current session.")

        project = await self.session.get(Project, state.project_id)
        if project is None:
            raise NotFoundError("Project not found.", details={"project_id": str(state.project_id)})

        _manifest, spec = self._oauth_manifest_and_spec(state.plugin_key)
        client = self._client_for(state.plugin_key)

        try:
            token = await client.exchange_code(spec, code=code, code_verifier=state.code_verifier)
        except TokenExchangeFailed as exc:
            raise PluginError(
                f"Failed to exchange authorization code with {state.plugin_key!r}: {exc}",
                plugin_key=state.plugin_key,
            ) from exc

        existing = await self.connections.get_by_project_plugin_and_label(
            state.project_id, state.plugin_key, state.label
        )
        is_reconnect = existing is not None
        connection = existing or PluginConnection(
            project_id=state.project_id, plugin_key=state.plugin_key, label=state.label
        )
        if not is_reconnect:
            self.session.add(connection)

        self._store_token(connection, token)
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=project.org_id,
                actor_user_id=current_user_id,
                action="plugin_connection.oauth_reconnected"
                if is_reconnect
                else "plugin_connection.oauth_connected",
                target=state.plugin_key,
            )
        )
        await self.session.flush()
        return connection

    async def disconnect(
        self, *, connection: PluginConnection, org_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> None:
        """Best-effort revokes at the provider (a failure here never blocks
        disconnection — see docs/auth/OAUTH2_ARCHITECTURE.md §6), then always clears local
        credentials and marks the connection disconnected."""
        _manifest, spec = self._oauth_manifest_and_spec(connection.plugin_key)

        has_stored_credentials = (
            connection.credentials_encrypted is not None
            and connection.credential_data_key_wrapped is not None
        )
        if has_stored_credentials:
            access_token = self._decrypt_access_token(connection)
            if access_token is not None:
                client = self._client_for(connection.plugin_key)
                await client.revoke(spec, token=access_token)

        connection.credentials_encrypted = None
        connection.credential_data_key_wrapped = None
        connection.token_expires_at = None
        connection.granted_scopes = []
        connection.status = PluginConnectionStatus.DISCONNECTED
        await self.session.flush()

        self.session.add(
            AuditLog(
                org_id=org_id,
                actor_user_id=actor_user_id,
                action="plugin_connection.oauth_disconnected",
                target=connection.plugin_key,
            )
        )
        await self.session.flush()

    def _oauth_manifest_and_spec(self, plugin_key: str) -> tuple[PluginManifest, OAuthProviderSpec]:
        manifest = self.catalog.get(plugin_key)
        if manifest is None:
            raise NotFoundError(
                f"No installed plugin with key {plugin_key!r}.", details={"plugin_key": plugin_key}
            )
        if manifest.auth_type != "oauth2" or manifest.oauth is None:
            raise ValidationError(
                f"Plugin {plugin_key!r} is not an OAuth2 plugin.",
                details={"plugin_key": plugin_key},
            )
        return manifest, manifest.oauth

    def _callback_url(self, plugin_key: str) -> str:
        return f"{self.settings.oauth_callback_base_url}/api/v1/oauth/{plugin_key}/callback"

    def _client_for(self, plugin_key: str) -> OAuthClient:
        client_id, client_secret = self.settings.oauth_client_credentials(plugin_key)
        return OAuthClient(
            client_id=client_id.get_secret_value(),
            client_secret=client_secret.get_secret_value(),
            redirect_uri=self._callback_url(plugin_key),
        )

    def _session_secret(self) -> str:
        return self.settings.secret_key.get_secret_value()

    def _master_key(self) -> bytes:
        return derive_master_key(self.settings.credential_master_key.get_secret_value())

    def _store_token(self, connection: PluginConnection, token: TokenResponse) -> None:
        payload = json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "token_type": token.token_type,
            }
        ).encode("utf-8")
        ciphertext, wrapped_data_key = envelope_encrypt(self._master_key(), payload)

        connection.credentials_encrypted = ciphertext
        connection.credential_data_key_wrapped = wrapped_data_key
        connection.token_expires_at = token.expires_at
        connection.granted_scopes = list(token.granted_scopes)
        connection.status = PluginConnectionStatus.CONNECTED

    def _decrypt_access_token(self, connection: PluginConnection) -> str | None:
        assert connection.credentials_encrypted is not None
        assert connection.credential_data_key_wrapped is not None
        plaintext = envelope_decrypt(
            self._master_key(),
            connection.credentials_encrypted,
            connection.credential_data_key_wrapped,
        )
        data = json.loads(plaintext)
        access_token = data.get("access_token")
        return access_token if isinstance(access_token, str) else None
