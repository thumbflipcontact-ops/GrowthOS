"""Verifies every column database/schema.sql declares with a DB-level DEFAULT actually has
one — not just a Python/ORM-side default, which wouldn't apply to a raw SQL insert. This is
a regression test for a real bug found during Phase 1 implementation: several models
initially only had ORM-side `default=`, so a direct SQL insert violated NOT NULL. See
docs/database/SCHEMA.md.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_project_jsonb_and_enum_defaults_apply_without_the_orm(engine) -> None:
    async with engine.begin() as conn:
        org_id = (
            await conn.execute(
                text("insert into organizations (name, slug) values ('Acme','acme-defaults') returning id")
            )
        ).scalar_one()
        row = (
            await conn.execute(
                text(
                    "insert into projects (org_id, name, slug) values (:org_id,'P','p-defaults') "
                    "returning icp_config, brand_voice, status"
                ),
                {"org_id": org_id},
            )
        ).one()
        assert row.icp_config == {}
        assert row.brand_voice == {}
        assert row.status == "active"


@pytest.mark.asyncio
async def test_plugin_connection_array_and_jsonb_defaults(engine) -> None:
    async with engine.begin() as conn:
        org_id = (
            await conn.execute(
                text("insert into organizations (name, slug) values ('Acme','acme-pc') returning id")
            )
        ).scalar_one()
        project_id = (
            await conn.execute(
                text(
                    "insert into projects (org_id, name, slug) values (:o,'P','p-pc') returning id"
                ),
                {"o": org_id},
            )
        ).scalar_one()
        row = (
            await conn.execute(
                text(
                    "insert into plugin_connections (project_id, plugin_key) "
                    "values (:p, 'dummy') returning capabilities_enabled, config, status"
                ),
                {"p": project_id},
            )
        ).one()
        assert list(row.capabilities_enabled) == []
        assert row.config == {}
        assert row.status == "disconnected"


@pytest.mark.asyncio
async def test_content_item_version_and_status_defaults(engine) -> None:
    async with engine.begin() as conn:
        org_id = (
            await conn.execute(
                text("insert into organizations (name, slug) values ('Acme','acme-ci') returning id")
            )
        ).scalar_one()
        project_id = (
            await conn.execute(
                text("insert into projects (org_id, name, slug) values (:o,'P','p-ci') returning id"),
                {"o": org_id},
            )
        ).scalar_one()
        row = (
            await conn.execute(
                text(
                    "insert into content_items (project_id, type, body) "
                    "values (:p, 'dummy_reply', 'hello') returning version, status"
                ),
                {"p": project_id},
            )
        ).one()
        assert row.version == 1
        assert row.status == "draft"


@pytest.mark.asyncio
async def test_timestamps_are_stored_with_timezone(engine) -> None:
    """Regression test for a real bug: several `Mapped[datetime]` columns were missing an
    explicit `DateTime(timezone=True)`, so Postgres stored them as naive TIMESTAMP —
    incompatible with the timezone-aware datetimes application code produces, and a
    mismatch against database/schema.sql's `timestamptz` columns."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "select column_name, data_type from information_schema.columns "
                "where table_name='domain_events' and column_name in ('occurred_at','dispatched_at')"
            )
        )
        types = {row.column_name: row.data_type for row in result}
    assert types["occurred_at"] == "timestamp with time zone"
    assert types["dispatched_at"] == "timestamp with time zone"


@pytest.mark.asyncio
async def test_review_fields_consistent_constraint_rejects_partial_review(engine) -> None:
    async with engine.begin() as conn:
        org_id = (
            await conn.execute(
                text("insert into organizations (name, slug) values ('Acme','acme-cc') returning id")
            )
        ).scalar_one()
        project_id = (
            await conn.execute(
                text("insert into projects (org_id, name, slug) values (:o,'P','p-cc') returning id"),
                {"o": org_id},
            )
        ).scalar_one()

    with pytest.raises(Exception, match="review_fields_consistent"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "insert into content_items (project_id, type, body, reviewed_at) "
                    "values (:p, 'dummy_reply', 'bad', now())"
                ),
                {"p": project_id},
            )


@pytest.mark.asyncio
async def test_gen_random_uuid_default_produces_a_real_uuid(engine) -> None:
    async with engine.begin() as conn:
        row = await conn.execute(text("insert into organizations (name, slug) values ('A','a-uuid') returning id"))
        generated_id = row.scalar_one()
    assert isinstance(generated_id, uuid.UUID)
