#!/usr/bin/env python3
"""Interactive first-run wizard: creates your organization, owner account, and first
project, then prints the exact next steps (with real IDs filled in) to get from here to a
running system. See docs/beta/FIRST_RUN_CHECKLIST.md and docs/beta/SETUP_GUIDE.md.

Run: python scripts/onboard.py
Safe to interrupt (Ctrl+C) at any prompt — nothing is written until you've answered every
question. Safe to re-run — a duplicate org/project slug is reported clearly, not corrupted.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))


def _prompt(label: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default:
            return default
        if value:
            return value
        print("  This can't be empty.")


def _slugify(text: str) -> str:
    return "-".join(text.lower().split())


def _read_password(prompt: str) -> str:
    """`getpass.getpass()` on Windows reads directly from the console (CONIN$) via msvcrt —
    this hangs indefinitely in mintty-based terminals (Git Bash's default), which don't
    provide a native Win32 console at all, rather than raising an error getpass could catch
    and fall back from. MSYSTEM is set by Git Bash/MSYS2 specifically — a reliable enough
    signal to skip straight to plain (visible) input there instead of hanging."""
    import os

    if os.name == "nt" and os.environ.get("MSYSTEM"):
        print("(Git Bash detected - password will be visible as you type, not hidden.)")
        return input(prompt)
    return getpass.getpass(prompt)


def _prompt_password() -> str:
    while True:
        password = _read_password("Password (min 8 characters, hidden while typing): ")
        if len(password) < 8:
            print("  Too short - use at least 8 characters.")
            continue
        confirm = _read_password("Confirm password: ")
        if password != confirm:
            print("  Passwords didn't match - try again.")
            continue
        return password


async def main() -> int:
    from app.core.config import get_settings
    from app.core.db import create_engine, create_session_factory
    from app.core.errors import ValidationError
    from app.models.project import Project
    from app.repositories.organization_repository import OrganizationRepository
    from app.repositories.project_repository import ProjectRepository
    from app.services.auth_service import AuthService

    print("GrowthOS onboarding")
    print("=" * 40)
    print("This creates your organization, owner account, and first project.")
    print("Nothing here connects to Reddit or Anthropic yet - that's a separate,")
    print("browser-based step this wizard will point you to at the end.\n")

    settings = get_settings()

    org_name = _prompt("Organization name", default="My Company")
    org_slug = _prompt("Organization slug (URL-safe id)", default=_slugify(org_name))
    email = _prompt("Your email")
    name = _prompt("Your name")
    password = _prompt_password()
    project_name = _prompt("First project name", default=org_name)
    project_slug = _prompt("Project slug (URL-safe id)", default=_slugify(project_name))

    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        try:
            user = await AuthService(session).register(
                org_name=org_name, org_slug=org_slug, email=email, name=name, password=password
            )
        except ValidationError as exc:
            print(f"\nCouldn't create the account: {exc.message}")
            print("If you already ran this wizard before, log in via POST /api/v1/auth/login")
            print("instead, or pick a different org slug / email.")
            await engine.dispose()
            return 1

        organization = await OrganizationRepository(session).get_by_slug(org_slug)
        assert organization is not None  # just created it above, in the same transaction

        existing = await ProjectRepository(session).get_by_slug(organization.id, project_slug)
        if existing is not None:
            print(f"\nProject slug {project_slug!r} already exists in this org - reusing it.")
            project = existing
        else:
            project = await ProjectRepository(session).add(
                Project(org_id=organization.id, name=project_name, slug=project_slug)
            )

        await session.commit()

    await engine.dispose()

    print("\nDone. Created:")
    print(f"  Organization: {org_name} ({org_slug})  id={organization.id}")
    print(f"  User:         {email}  id={user.id}")
    print(f"  Project:      {project_name} ({project_slug})  id={project.id}")

    print("\nNext steps:")
    print("  1. Start the backend + background workers - see docs/beta/SETUP_GUIDE.md")
    print("     (`docs/deployment/DEPLOYMENT.md`'s \"Non-Docker deployment\" for the exact commands).")
    print("  2. Log in: POST /api/v1/auth/login with your email/password above - this sets")
    print("     the session cookie every other request needs.")
    print("  3. Connect Reddit (requires a browser - see docs/beta/SETUP_GUIDE.md for how to")
    print("     register a Reddit app first):")
    print(f"       POST /api/v1/projects/{project.id}/plugin-connections")
    print('         {"plugin_key": "reddit", "config": {"subreddits": ["YOUR_SUBREDDIT"]},')
    print('          "capabilities_enabled": ["searchable", "publishable"]}')
    print(f"       POST /api/v1/projects/{project.id}/plugin-connections/reddit/oauth/start")
    print("         -> open the returned authorize_url in a browser and approve access")
    print("  4. Configure the agents - see docs/examples/ for ready-to-use payloads:")
    print(f"       PUT /api/v1/projects/{project.id}/agent-configs/conversation_finder")
    print(f"       PUT /api/v1/projects/{project.id}/agent-configs/content_agent")
    print("  5. Trigger a run on demand instead of waiting for the schedule:")
    print(f"       POST /api/v1/projects/{project.id}/agent-configs/conversation_finder/runs/trigger")
    print("  6. Watch progress any time with: python scripts/status.py")
    print("\nSee docs/beta/FIRST_RUN_CHECKLIST.md for the full, step-by-step version of this.")
    return 0


if __name__ == "__main__":
    from _bootstrap import ensure_running_under_backend_venv

    ensure_running_under_backend_venv(__file__)
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nCancelled - nothing was created.")
        sys.exit(1)
