"""LinkedIn plugin — Publishable only (no search() — see README §"Why no search()"). See
plugins/linkedin/README.md, docs/plugins/PLUGIN_ARCHITECTURE.md, and
docs/auth/OAUTH2_ARCHITECTURE.md.
"""

from __future__ import annotations

from plugins._shared.base import PublishResult, ResolvedConnection
from plugins._shared.credentials import OAuth2Credentials
from plugins._shared.rate_limit import RateLimiter
from plugins.linkedin.client import LinkedInAPIError, LinkedInClient
from plugins.linkedin.manifest import MANIFEST, LinkedInConnectionConfig

# One shared limiter across every LinkedInPlugin instance in this process — a fresh instance
# is constructed on every registry lookup (app/core/plugin_registry.py), so per-instance
# state would reset each call and never actually limit anything. LinkedIn does not publish a
# simple, fixed per-app rate limit the way Reddit/X do — this is a deliberately conservative
# placeholder (25 calls/day) pending real numbers once this plugin is actually approved and
# connected; see README §"Rate limits".
_RATE_LIMITER = RateLimiter(capacity=25, refill_rate=25 / 86_400)


class LinkedInPlugin:
    manifest = MANIFEST

    def __init__(self, connection: ResolvedConnection) -> None:
        self._connection = connection
        self._config = LinkedInConnectionConfig.model_validate(connection.config)
        self._client = _build_client(connection)

    async def publish(self, item: object) -> PublishResult:
        if self._client is None:
            return PublishResult(
                success=False,
                published_url=None,
                error="This LinkedIn connection has no valid credentials yet — connect or "
                "reconnect it.",
            )

        body = getattr(item, "body", None)
        if not body:
            return PublishResult(success=False, published_url=None, error="item is missing body.")

        if not self._try_acquire():
            return PublishResult(
                success=False, published_url=None, error="Rate limited — try again shortly."
            )

        try:
            # Two LinkedIn calls (resolve the member's URN, then create the post) charged as
            # one unit of this plugin's own budget above — they always happen together as a
            # single logical publish, so billing them separately would just halve the
            # effective capacity for no real benefit. See client.py's create_post docstring.
            userinfo = await self._client.userinfo()
            person_id = userinfo.get("sub")
            if not person_id:
                return PublishResult(
                    success=False,
                    published_url=None,
                    error="Could not determine the LinkedIn member id — userinfo response "
                    "was missing 'sub'.",
                )
            response = await self._client.create_post(
                person_id=person_id, text=body, visibility=self._config.visibility
            )
        except LinkedInAPIError as exc:
            return PublishResult(success=False, published_url=None, error=str(exc))

        return PublishResult(success=True, published_url=_published_url(response), error=None)

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.userinfo()
        except LinkedInAPIError:
            return False
        return True

    def _try_acquire(self) -> bool:
        return _RATE_LIMITER.try_acquire(
            plugin_key=self._connection.plugin_key, project_id=str(self._connection.project_id)
        )


def _build_client(connection: ResolvedConnection) -> LinkedInClient | None:
    if not isinstance(connection.credentials, OAuth2Credentials):
        return None
    return LinkedInClient(access_token=connection.credentials.access_token)


def _published_url(response: dict) -> str | None:
    post_id = response.get("id")
    return f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else None


def create_plugin(connection: ResolvedConnection) -> LinkedInPlugin:
    return LinkedInPlugin(connection)
