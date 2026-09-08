"""Turns raw token counts into an actual dollar cost — see app/models/llm_usage.py and
app/services/llm_usage.py, the only caller.

Anthropic's API returns a fully-qualified, dated model id in `CompletionResult.model` (e.g.
"claude-sonnet-4-5-20250929"), not the shorter alias `Settings.anthropic_model` configures
(e.g. "claude-sonnet-4-5") — matching is done by prefix, longest first, so either form (and
any future dated snapshot of the same model family) resolves to the same rate without needing
a table entry per dated release.

Rates are per Anthropic's published pricing at the time this was written — update
`_RATES_USD_PER_MILLION_TOKENS` if pricing changes; nothing else in this module needs to.
"""

from __future__ import annotations

from decimal import Decimal

# (input $/M tokens, output $/M tokens). Ordered longest-prefix-first so e.g.
# "claude-sonnet-4-5" is checked before a hypothetical shorter "claude-sonnet-4" entry.
_RATES_USD_PER_MILLION_TOKENS: list[tuple[str, Decimal, Decimal]] = [
    ("claude-sonnet-4-5", Decimal("3.00"), Decimal("15.00")),
    ("claude-opus-4", Decimal("15.00"), Decimal("75.00")),
    ("claude-haiku-4-5", Decimal("1.00"), Decimal("5.00")),
]
_RATES_BY_PREFIX_LENGTH = sorted(
    _RATES_USD_PER_MILLION_TOKENS, key=lambda entry: len(entry[0]), reverse=True
)

# Used only when `model` matches no known prefix (a new/renamed model this table hasn't been
# updated for yet) — deliberately the most expensive known rate, not zero: an unrecognized
# model logging as free would silently understate real spend, exactly the blind spot this
# table exists to close. A cost row still gets written either way; this only picks the rate.
_FALLBACK_RATES = max(_RATES_USD_PER_MILLION_TOKENS, key=lambda entry: entry[1])


def estimate_cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    input_rate, output_rate = _FALLBACK_RATES[1], _FALLBACK_RATES[2]
    for prefix, in_rate, out_rate in _RATES_BY_PREFIX_LENGTH:
        if model.startswith(prefix):
            input_rate, output_rate = in_rate, out_rate
            break

    cost = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(
        "1000000"
    )
    return cost.quantize(Decimal("0.000001"))
