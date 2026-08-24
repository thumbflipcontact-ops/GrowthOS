"""Proves `alembic upgrade head` actually produces database/schema.sql's shape — see
docs/database/SCHEMA.md and the _migrated_db fixture in tests/conftest.py."""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "organizations",
    "users",
    "password_reset_tokens",
    "memberships",
    "projects",
    "plugin_catalog",
    "plugin_connections",
    "agent_configs",
    "agent_runs",
    "domain_events",
    "knowledge_items",
    "content_items",
    "content_publish_attempts",
    "audit_log",
    "companies",
    "contacts",
    "competitors",
    "competitor_observations",
    "daily_briefs",
    "subscriptions",
    "api_keys",
    "webhook_subscriptions",
    "webhook_deliveries",
}

EXPECTED_ENUMS = {
    "membership_role",
    "project_status",
    "plugin_capability",
    "plugin_connection_status",
    "agent_run_status",
    "buying_intent",
    "content_item_status",
    "contact_status",
    "subscription_status",
    "webhook_delivery_status",
}


@pytest.mark.asyncio
async def test_migration_creates_every_table_in_schema_sql(engine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("select table_name from information_schema.tables where table_schema='public'")
        )
        tables = {row[0] for row in result} - {"alembic_version"}
    assert tables == EXPECTED_TABLES


@pytest.mark.asyncio
async def test_migration_creates_every_core_owned_enum(engine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "select distinct typname from pg_type join pg_enum "
                "on pg_enum.enumtypid = pg_type.oid"
            )
        )
        enums = {row[0] for row in result}
    assert enums == EXPECTED_ENUMS


@pytest.mark.asyncio
async def test_content_item_type_is_not_an_enum(engine) -> None:
    """content_items.type must be plugin-contributed text, never a closed database enum —
    see docs/decisions/0008-plugin-contributed-content-types.md."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "select data_type from information_schema.columns "
                "where table_name='content_items' and column_name='type'"
            )
        )
        (data_type,) = result.one()
    assert data_type == "text"


@pytest.mark.asyncio
async def test_vector_extension_is_installed(engine) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("select extname from pg_extension where extname='vector'"))
        assert result.first() is not None
