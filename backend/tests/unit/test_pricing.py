"""See app/core/pricing.py — pure math, no DB, so covered directly at the boundary values."""

from __future__ import annotations

from app.core.pricing import tier_for_count, tier_statuses


def test_first_five_signups_land_in_founding_tier() -> None:
    for count in range(5):
        assert tier_for_count(count).key == "founding"


def test_next_ten_signups_land_in_early_tier() -> None:
    for count in range(5, 15):
        assert tier_for_count(count).key == "early"


def test_signups_past_fifteen_land_in_standard_tier() -> None:
    for count in (15, 16, 100):
        assert tier_for_count(count).key == "standard"


def test_tier_statuses_at_zero_signups() -> None:
    founding, early, standard = tier_statuses(0)
    assert (founding.spots_taken, founding.spots_left, founding.is_current, founding.is_sold_out) == (
        0,
        5,
        True,
        False,
    )
    assert (early.is_current, early.is_sold_out) == (False, False)
    assert (standard.spots_taken, standard.is_current) == (0, False)


def test_tier_statuses_when_founding_exactly_sold_out() -> None:
    founding, early, standard = tier_statuses(5)
    assert founding.is_sold_out is True
    assert founding.spots_left == 0
    assert early.is_current is True
    assert early.spots_taken == 0
    assert early.spots_left == 10


def test_tier_statuses_partway_into_standard_tier() -> None:
    founding, early, standard = tier_statuses(20)
    assert founding.is_sold_out is True
    assert early.is_sold_out is True
    assert standard.is_current is True
    assert standard.spots_taken == 5
    assert standard.spots_left is None
