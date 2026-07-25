"""Declarative base and shared column mixins for every model in app/models/.

Mirrors the conventions stated at the top of database/schema.sql: UUID primary keys
(server-generated via gen_random_uuid(), a Postgres 13+ core builtin — see schema.sql),
created_at on every table, updated_at on mutable ones, no soft deletes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    # database/schema.sql uses `text` for every unbounded string column, never `varchar`.
    # Without this, SQLAlchemy's default type inference for `Mapped[str]` is `VARCHAR`
    # (reported as `character varying` in Postgres) — functionally near-identical to `text`
    # for unbounded columns, but a mismatch against the frozen source-of-truth DDL. Mapping
    # it once here means every model's plain `Mapped[str]` column matches schema.sql without
    # needing an explicit `Text` type annotation on every single column.
    type_annotation_map = {str: Text}


class UUIDPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Every core-owned enum in this schema (see database/schema.sql's top-of-file
    convention note) is a `str` subclass whose Postgres type should store the lowercase
    `.value`, not the Python member name — this is the one-line helper every model's enum
    column uses instead of repeating `values_callable=lambda e: [m.value for m in e]`."""
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])
