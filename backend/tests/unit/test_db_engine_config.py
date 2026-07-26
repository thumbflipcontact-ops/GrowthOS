"""Unit test for app/core/db.py's pool_size/max_overflow threading — see
docs/reviews/PRODUCTION_READINESS_REVIEW.md SC2. create_async_engine doesn't connect eagerly,
so this doesn't need a real database.
"""

from __future__ import annotations

from app.core.db import create_engine


def test_create_engine_applies_custom_pool_settings() -> None:
    engine = create_engine(
        "postgresql://u:p@localhost:5432/x", pool_size=20, max_overflow=40
    )
    try:
        assert engine.pool.size() == 20
    finally:
        engine.sync_engine.dispose()


def test_create_engine_defaults_match_sqlalchemys_prior_implicit_defaults() -> None:
    engine = create_engine("postgresql://u:p@localhost:5432/x")
    try:
        assert engine.pool.size() == 5
    finally:
        engine.sync_engine.dispose()
