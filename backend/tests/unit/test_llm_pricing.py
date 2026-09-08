"""See app/core/llm/pricing.py."""

from __future__ import annotations

from decimal import Decimal

from app.core.llm.pricing import estimate_cost_usd


def test_estimate_cost_usd_matches_a_known_model_by_prefix() -> None:
    # Anthropic reports a dated snapshot id, not the short alias Settings.anthropic_model
    # configures — this must still resolve to the claude-sonnet-4-5 rate.
    cost = estimate_cost_usd(
        model="claude-sonnet-4-5-20250929", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert cost == Decimal("18.000000")  # $3 input + $15 output per million tokens


def test_estimate_cost_usd_is_zero_for_zero_tokens() -> None:
    assert estimate_cost_usd(model="claude-sonnet-4-5", input_tokens=0, output_tokens=0) == 0


def test_estimate_cost_usd_falls_back_to_the_most_expensive_known_rate_for_an_unknown_model() -> (
    None
):
    # An unrecognized model (this table not yet updated for a new release) must never log as
    # free — that would silently understate real spend, the exact blind spot this exists to
    # close. It should cost at least as much as the priciest model this table does know.
    unknown = estimate_cost_usd(model="claude-future-model-x", input_tokens=1000, output_tokens=0)
    known_cheapest = estimate_cost_usd(
        model="claude-haiku-4-5", input_tokens=1000, output_tokens=0
    )
    assert unknown >= known_cheapest


def test_estimate_cost_usd_scales_linearly_with_tokens() -> None:
    single = estimate_cost_usd(model="claude-sonnet-4-5", input_tokens=100, output_tokens=100)
    double = estimate_cost_usd(model="claude-sonnet-4-5", input_tokens=200, output_tokens=200)
    assert double == single * 2
