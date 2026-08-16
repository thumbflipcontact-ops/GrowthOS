"""Transactional email — see app/core/agent_lifecycle.py, its only caller so far.

The only code in the system that sends email. Provider-specific (Resend) on purpose, unlike
app/core/oauth/'s provider-agnostic design — there's exactly one email need today
(system-triggered notifications), not a plugin ecosystem of providers to abstract over.
"""

from __future__ import annotations
