"""Generic, provider-agnostic OAuth2 client — see docs/auth/OAUTH2_ARCHITECTURE.md §1 and ADR
0011. The ONLY code in the system that makes HTTP calls to a plugin's declared
`authorize_url`/`token_url`/`revoke_url`. Executes RFC 6749's authorization-code grant, with
optional RFC 7636 PKCE, against whatever `OAuthProviderSpec` a plugin's manifest declares —
nothing here is specific to any one provider (Reddit, Google, Slack, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from plugins._shared.oauth import OAuthProviderSpec

from app.core.oauth.errors import PermanentRefreshFailure, TokenExchangeFailed

_HTTP_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime
    granted_scopes: tuple[str, ...]


class OAuthClient:
    """One instance per (plugin, request) — `client_id`/`client_secret` are the operator's
    app-registration credentials for this plugin (from `Settings`, never per-connection data;
    see docs/auth/OAUTH2_ARCHITECTURE.md §6), `redirect_uri` is the fixed, configured callback
    URL registered with the provider (never derived from request data)."""

    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def build_authorize_url(
        self, spec: OAuthProviderSpec, *, state: str, code_challenge: str | None = None
    ) -> str:
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(spec.scopes),
            "state": state,
            **spec.extra_authorize_params,
        }
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{spec.authorize_url}?{urlencode(params)}"

    async def exchange_code(
        self, spec: OAuthProviderSpec, *, code: str, code_verifier: str | None = None
    ) -> TokenResponse:
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            **spec.extra_token_params,
        }
        if code_verifier is not None:
            data["code_verifier"] = code_verifier
        return await self._post_token(spec, data)

    async def refresh(self, spec: OAuthProviderSpec, *, refresh_token: str) -> TokenResponse:
        """Raises `PermanentRefreshFailure` (a `TokenExchangeFailed` subclass) specifically
        when the provider reports `invalid_grant` — the refresh token itself is dead and
        retrying will never help. Any other failure (network error, provider 5xx, a
        differently-coded error) raises the base `TokenExchangeFailed`, which the refresh
        sweep (app/jobs/oauth_refresh.py) treats as transient and simply retries next cycle.
        See docs/auth/OAUTH2_ARCHITECTURE.md §2, §5.2."""
        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            **spec.extra_token_params,
        }
        try:
            return await self._post_token(spec, data)
        except TokenExchangeFailed as exc:
            if exc.provider_error == "invalid_grant":
                raise PermanentRefreshFailure(str(exc), provider_error=exc.provider_error) from exc
            raise

    async def revoke(self, spec: OAuthProviderSpec, *, token: str) -> None:
        """Best-effort — see docs/auth/OAUTH2_ARCHITECTURE.md §6: disconnection always
        proceeds locally regardless of whether this succeeds. Silently returns if the plugin
        declares no `revoke_url`."""
        if spec.revoke_url is None:
            return
        auth = self._basic_auth(spec)
        headers = spec.extra_token_headers or None
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                if auth is not None:
                    await client.post(
                        spec.revoke_url, data={"token": token}, headers=headers, auth=auth
                    )
                else:
                    await client.post(spec.revoke_url, data={"token": token}, headers=headers)
        except httpx.HTTPError:
            pass  # best-effort — the caller clears local credentials regardless

    def _basic_auth(self, spec: OAuthProviderSpec) -> httpx.BasicAuth | None:
        if spec.token_endpoint_auth_method == "client_secret_basic":
            return httpx.BasicAuth(self.client_id, self.client_secret)
        return None

    async def _post_token(self, spec: OAuthProviderSpec, data: dict[str, str]) -> TokenResponse:
        if spec.token_endpoint_auth_method == "client_secret_post":
            data = {**data, "client_id": self.client_id, "client_secret": self.client_secret}
        auth = self._basic_auth(spec)

        headers = {"Accept": "application/json", **spec.extra_token_headers}

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                # httpx's `auth` parameter has no typed `None` variant (it defaults to a
                # sentinel meaning "no override"), so the kwarg is omitted entirely for a
                # provider that doesn't use HTTP Basic client auth, rather than passed as
                # `None` — hence the branch instead of always passing `auth=auth`.
                if auth is not None:
                    response = await client.post(
                        spec.token_url, data=data, headers=headers, auth=auth
                    )
                else:
                    response = await client.post(spec.token_url, data=data, headers=headers)
        except httpx.HTTPError as exc:
            raise TokenExchangeFailed(f"Could not reach token endpoint: {exc}") from exc

        body = _safe_json(response)

        if response.status_code >= 400:
            provider_error = body.get("error") if isinstance(body, dict) else None
            raise TokenExchangeFailed(
                f"Token endpoint returned {response.status_code}: {response.text[:500]}",
                provider_error=provider_error,
            )

        if not isinstance(body, dict) or "access_token" not in body:
            raise TokenExchangeFailed(
                f"Token endpoint response missing access_token: {response.text[:500]}"
            )

        try:
            expires_in = int(body.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600

        granted_scope = body.get("scope")
        granted_scopes = tuple(granted_scope.split()) if granted_scope else spec.scopes

        return TokenResponse(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            token_type=body.get("token_type", "bearer"),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            granted_scopes=granted_scopes,
        )


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


__all__ = ["OAuthClient", "TokenResponse"]
