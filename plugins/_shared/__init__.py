"""The plugin SDK's public surface — re-exports the common types from base.py, manifest.py,
events.py, and rate_limit.py so a plugin author can write one import instead of four:

    from plugins._shared import (
        PluginManifest, ContentTypeSpec,
        Searchable, PluginQuery, PluginResult,
    )

instead of separately importing from `plugins._shared.base`, `plugins._shared.manifest`,
etc. Importing from the submodules directly still works and is equally correct — this is
purely an ergonomics addition, not a new contract.
"""

from __future__ import annotations

from plugins._shared.base import (
    CapabilityNotSupported,
    GrowthOSPlugin,
    MetricsQueryable,
    MetricsQuerySpec,
    MetricsResult,
    PluginQuery,
    PluginResult,
    Publishable,
    PublishResult,
    ResolvedConnection,
    Searchable,
    WebhookReceivable,
)
from plugins._shared.credentials import ApiKeyCredentials, Credentials, OAuth2Credentials
from plugins._shared.events import DomainEventPublisher
from plugins._shared.manifest import AuthType, ContentTypeSpec, PluginCapabilityName, PluginManifest
from plugins._shared.oauth import OAuthProviderSpec, PKCEPolicy, TokenEndpointAuthMethod
from plugins._shared.rate_limit import RateLimiter

__all__ = [
    "ApiKeyCredentials",
    "AuthType",
    "CapabilityNotSupported",
    "ContentTypeSpec",
    "Credentials",
    "DomainEventPublisher",
    "GrowthOSPlugin",
    "MetricsQueryable",
    "MetricsQuerySpec",
    "MetricsResult",
    "OAuth2Credentials",
    "OAuthProviderSpec",
    "PKCEPolicy",
    "PluginCapabilityName",
    "PluginManifest",
    "PluginQuery",
    "PluginResult",
    "Publishable",
    "PublishResult",
    "RateLimiter",
    "ResolvedConnection",
    "Searchable",
    "TokenEndpointAuthMethod",
    "WebhookReceivable",
]
