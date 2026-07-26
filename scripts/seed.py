#!/usr/bin/env python3
"""Seeds a local dev database with a demo org/user/project — never runs against
staging/production (refuses unless ENVIRONMENT=local). See scripts/README.md.

Run: python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))


async def main() -> None:
    from app.core.config import get_settings
    from app.core.db import create_engine, create_session_factory
    from app.services.auth_service import AuthService

    settings = get_settings()
    if settings.environment != "local":
        raise SystemExit(
            f"Refusing to seed a non-local environment (ENVIRONMENT={settings.environment!r})."
        )

    engine = create_engine(str(settings.database_url))
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        service = AuthService(session)
        try:
            user = await service.register(
                org_name="Demo Org",
                org_slug="demo-org",
                email="founder@demo.local",
                name="Demo Founder",
                password="demo-password-change-me",
            )
            await session.commit()
            print(f"Seeded demo org 'demo-org' with user {user.email} (password: demo-password-change-me)")
        except Exception as exc:
            print(f"Seed skipped (already seeded?): {exc}")

    await engine.dispose()


if __name__ == "__main__":
    from _bootstrap import ensure_running_under_backend_venv

    ensure_running_under_backend_venv(__file__)
    asyncio.run(main())
