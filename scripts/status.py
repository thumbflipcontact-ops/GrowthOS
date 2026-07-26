#!/usr/bin/env python3
"""Read-only operational status dashboard — a quick "what's actually going on" snapshot
without needing to hand-write SQL or curl every API endpoint. See
docs/beta/TROUBLESHOOTING_GUIDE.md.

Run: python scripts/status.py [--project SLUG]
Prints every org/project by default; --project narrows to one project by slug.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))


def _section(title: str) -> None:
    print(f"\n== {title} ==")


async def _print_project_status(session, project) -> None:
    from app.repositories.agent_repository import AgentConfigRepository, AgentRunRepository
    from app.repositories.content_repository import ContentItemRepository
    from app.repositories.plugin_repository import PluginConnectionRepository

    print(f"\nProject: {project.name} ({project.slug})  id={project.id}")

    connections = await PluginConnectionRepository(session).list_by_project(project.id)
    if not connections:
        print("  Plugin connections: none")
    else:
        print("  Plugin connections:")
        for c in connections:
            caps = ", ".join(c.capabilities_enabled) or "(none enabled)"
            print(f"    - {c.plugin_key} [{c.label}] status={c.status.value}  capabilities={caps}")
            if c.status.value in ("expired", "error"):
                print("      -> needs reconnecting: POST .../plugin-connections/"
                      f"{c.plugin_key}/oauth/start")

    configs = await AgentConfigRepository(session).list_by_project(project.id)
    if not configs:
        print("  Agent configs: none configured yet")
    else:
        print("  Agent configs:")
        for a in configs:
            state = "enabled" if a.enabled else "disabled"
            schedule = a.schedule_cron or "(event-triggered only, no schedule)"
            print(f"    - {a.agent_key}: {state}, schedule={schedule}")

    runs = await AgentRunRepository(session).list_by_project(project.id, limit=20)
    if not runs:
        print("  Agent runs: none yet")
    else:
        counts = Counter(r.status.value for r in runs)
        summary = ", ".join(f"{status}={n}" for status, n in counts.items())
        print(f"  Agent runs (last {len(runs)}): {summary}")
        most_recent = runs[0]
        print(
            f"    most recent: {most_recent.agent_key} {most_recent.status.value} "
            f"at {most_recent.created_at.isoformat()}"
            + (f" -- {most_recent.error}" if most_recent.error else "")
        )

    items = await ContentItemRepository(session).list_by_project(project.id, limit=200)
    if not items:
        print("  Content items: none yet")
    else:
        counts = Counter(i.status.value for i in items)
        summary = ", ".join(f"{status}={n}" for status, n in sorted(counts.items()))
        print(f"  Content items (up to 200 most recent): {summary}")
        failing = [i for i in items if i.status.value == "approved" and i.publish_error]
        if failing:
            print(f"  ! {len(failing)} approved item(s) with a publish error - needs attention:")
            for i in failing[:5]:
                print(f"      - {i.id}: {i.publish_error}")
            print("    Retry via: POST .../content-items/{id}/retry-publish")
        pending = counts.get("pending_review", 0)
        if pending:
            print(f"  {pending} item(s) awaiting your review - GET .../content-items?status=pending_review")


async def main() -> int:
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.core.db import create_engine, create_session_factory
    from app.models.event import DomainEvent
    from app.repositories.organization_repository import OrganizationRepository
    from app.repositories.project_repository import ProjectRepository

    project_slug_filter = None
    args = sys.argv[1:]
    if "--project" in args:
        idx = args.index("--project")
        project_slug_filter = args[idx + 1]

    settings = get_settings()
    engine = create_engine(
        str(settings.database_url),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        orgs = await OrganizationRepository(session).list_all()
        if not orgs:
            print("No organizations exist yet - run `python scripts/onboard.py` first.")
            await engine.dispose()
            return 0

        _section("Organizations & projects")
        any_project = False
        for org in orgs:
            projects = await ProjectRepository(session).list_by_org(org.id)
            for project in projects:
                if project_slug_filter and project.slug != project_slug_filter:
                    continue
                any_project = True
                await _print_project_status(session, project)

        if not any_project:
            if project_slug_filter:
                print(f"No project found with slug {project_slug_filter!r}.")
            else:
                print("No projects exist yet.")

        _section("Event dispatch backlog (all projects)")
        undispatched = await session.execute(
            select(DomainEvent).where(DomainEvent.dispatched_at.is_(None)).limit(500)
        )
        pending_events = list(undispatched.scalars().all())
        if pending_events:
            oldest = min(pending_events, key=lambda e: e.occurred_at)
            print(
                f"{len(pending_events)} undispatched event(s) - oldest is "
                f"{oldest.event_type} from {oldest.occurred_at.isoformat()}."
            )
            print("If this number keeps growing, worker-events isn't running or is stuck -")
            print("see docs/beta/TROUBLESHOOTING_GUIDE.md.")
        else:
            print("0 undispatched events - event dispatch is keeping up.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    from _bootstrap import ensure_running_under_backend_venv

    ensure_running_under_backend_venv(__file__)
    sys.exit(asyncio.run(main()))
