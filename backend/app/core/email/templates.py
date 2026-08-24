"""Email copy for app/core/agent_lifecycle.py's two auto-disable reasons. Kept as plain
functions returning (subject, html_body) rather than a templating engine — there are exactly
two emails today, not a growing library of them.
"""

from __future__ import annotations

from html import escape


def conversation_finder_disabled_inactivity(
    *, user_name: str, project_name: str
) -> tuple[str, str]:
    name = escape(user_name)
    project = escape(project_name)
    subject = "Your Conversation Finder agent was paused — log back in to resume"
    html_body = f"""
    <p>Hi {name},</p>
    <p>We noticed no one has logged into <strong>{project}</strong> on Threadly for the last 48
    hours, so we've automatically turned off the Conversation Finder agent to avoid running up
    search costs while your account is inactive.</p>
    <p>Nothing else has changed — your settings and results are exactly where you left them.
    Just log back in and re-enable Conversation Finder from your project's agent settings
    whenever you're ready to pick back up.</p>
    <p>— The Threadly Team</p>
    """.strip()
    return subject, html_body


def conversation_finder_disabled_not_entitled(
    *, user_name: str, project_name: str
) -> tuple[str, str]:
    name = escape(user_name)
    project = escape(project_name)
    subject = "Your Conversation Finder agent was paused — subscribe to turn it back on"
    html_body = f"""
    <p>Hi {name},</p>
    <p>Your free trial for <strong>{project}</strong> has ended without an active subscription,
    so we've automatically turned off the Conversation Finder agent — it uses real, metered
    X/Twitter API calls that only run for subscribed accounts.</p>
    <p>Everything else about your project is untouched. Subscribe anytime from your billing
    settings and you can re-enable Conversation Finder immediately.</p>
    <p>— The Threadly Team</p>
    """.strip()
    return subject, html_body


def password_reset_requested(*, user_name: str, reset_url: str) -> tuple[str, str]:
    name = escape(user_name)
    # reset_url is our own server-generated link (frontend_origin + a urlsafe token), not
    # user-controlled input, but escaped anyway on the same "never interpolate raw" habit as
    # the other templates.
    url = escape(reset_url)
    subject = "Reset your Threadly password"
    html_body = f"""
    <p>Hi {name},</p>
    <p>We received a request to reset your Threadly password. Click the link below to choose
    a new one — it expires in 1 hour and can only be used once.</p>
    <p><a href="{url}">Reset your password</a></p>
    <p>If you didn't request this, you can safely ignore this email — your password hasn't
    been changed.</p>
    <p>— The Threadly Team</p>
    """.strip()
    return subject, html_body


__all__ = [
    "conversation_finder_disabled_inactivity",
    "conversation_finder_disabled_not_entitled",
    "password_reset_requested",
]
