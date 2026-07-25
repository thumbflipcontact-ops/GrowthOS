"""OAuth-flow error hierarchy — see docs/auth/OAUTH2_ARCHITECTURE.md.

Kept separate from app/core/errors.py's HTTP-mapped domain exceptions: these are
protocol-level errors raised by app/core/oauth/client.py, translated into the app-wide domain
exceptions at the service/API boundary (app/services/oauth_connection.py), the same pattern
plugins/_shared.base.CapabilityNotSupported already uses at the plugin registry boundary.
"""

from __future__ import annotations


class OAuthError(Exception):
    """Base for all OAuth-flow errors."""


class InvalidState(OAuthError):
    """The `state` parameter failed signature/age verification, or its embedded `user_id`
    didn't match the currently authenticated session — see
    docs/auth/OAUTH2_ARCHITECTURE.md §6."""


class TokenExchangeFailed(OAuthError):
    """The provider's token endpoint could not be reached, or returned an error response
    exchanging a code or refreshing a token. `provider_error` is the raw OAuth error code the
    provider returned (e.g. `"invalid_grant"`, `"invalid_client"`), when available."""

    def __init__(self, message: str, *, provider_error: str | None = None) -> None:
        super().__init__(message)
        self.provider_error = provider_error


class PermanentRefreshFailure(TokenExchangeFailed):
    """A refresh failure that will never succeed by retrying — `invalid_grant` (the refresh
    token itself is dead: revoked, expired, or the user revoked access). Distinguishes from a
    transient `TokenExchangeFailed` (network error, provider 5xx) that the refresh sweep
    should simply retry next cycle without changing connection status. See
    docs/auth/OAUTH2_ARCHITECTURE.md §2, §5.2."""


class OAuthClientNotConfigured(OAuthError):
    """The operator hasn't set `{PLUGIN_KEY}_OAUTH_CLIENT_ID`/`_CLIENT_SECRET` for this
    plugin — see app/core/config.py's `Settings.oauth_client_credentials()`. Raised at first
    use (when a connection attempt is actually initiated for this plugin), not at process
    startup — see docs/auth/OAUTH2_ARCHITECTURE.md §6."""


__all__ = [
    "InvalidState",
    "OAuthClientNotConfigured",
    "OAuthError",
    "PermanentRefreshFailure",
    "TokenExchangeFailed",
]
