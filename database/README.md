# Database

[`schema.sql`](schema.sql) is the design source of truth for GrowthOS's PostgreSQL schema.
See [`docs/database/SCHEMA.md`](../docs/database/SCHEMA.md) for the reasoning behind each
table and [`docs/database/ERD.md`](../docs/database/ERD.md) for the entity relationship
diagram.

Actual schema changes ship as Alembic migrations under `backend/migrations/` (Phase 1,
not yet implemented — see `ROADMAP.md`), generated from SQLAlchemy models that mirror this
file. When `schema.sql` and the migrations diverge, the migrations — what actually ran
against a real database — are correct, and this file should be updated to match.
