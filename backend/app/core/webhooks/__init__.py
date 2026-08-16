"""Outbound webhook delivery for the public API — see app/core/webhooks/dispatcher.py.

The only code in the system that makes HTTP calls to a `webhook_subscriptions.target_url`
(a URL supplied by a project owner, not this codebase's own operator).
"""

from __future__ import annotations
