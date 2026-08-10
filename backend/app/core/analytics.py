"""Optional server-side product-analytics capture. Mirrors app/core/observability.py's
"no-op unless the env var is set" pattern exactly (POSTHOG_API_KEY here instead of
SENTRY_DSN) — nothing about existing behavior changes if it isn't configured.

Only one event is captured from here: "subscribed" (BillingService._sync_subscription, the
first time an org's subscription is created). Every other funnel step — signup, connecting a
plugin, approving a draft, starting checkout — is captured client-side in the browser instead
(see frontend/lib/posthog.ts). This one specifically needs to be server-side: it's the only
step where webhook-verified truth from Polar matters more than whether the browser's redirect
back from Checkout ever completes. Someone can close the tab right after paying and the
frontend would never know; the webhook always fires regardless.

Both sides are identified by the same org id (see frontend/lib/useSession.ts's
posthog.identify(organization.id)), so this event lands in the same per-org timeline as the
frontend funnel steps, letting a single PostHog funnel span both.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

_client: Any | None = None


def init_analytics(settings: Settings) -> None:
    """Idempotent per-process init — safe to call from every process's startup, same
    convention as app/core/observability.py's init_error_tracking. No-ops if
    POSTHOG_API_KEY isn't configured."""
    global _client
    if _client is not None or not settings.posthog_api_key:
        return

    from posthog import Posthog

    _client = Posthog(project_api_key=settings.posthog_api_key, host=settings.posthog_host)


def capture(distinct_id: str, event: str, **properties: object) -> None:
    """No-op if analytics isn't initialized."""
    if _client is None:
        return
    _client.capture(event, distinct_id=distinct_id, properties=properties)
