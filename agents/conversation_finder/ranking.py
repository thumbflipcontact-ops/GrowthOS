"""Rule-based relevance scoring for discovered conversations. See README.md §Ranking.

Phase 2A has no LLM integration (ROADMAP.md, out of scope) — `KnowledgeItem.confidence` here
means "how well this result matches the configured search terms," a deterministic,
keyword-based score, not an LLM's judgment of buying intent. `problem`/`industry`/`product`/
`pain_point`/`buying_intent`/`suggested_*` stay at their schema defaults until a future
LLM-enrichment pass (docs/knowledge-base/KNOWLEDGE_BASE.md) fills them in — see
docs/reviews/CONVERSATION_FINDER_IMPLEMENTATION_REPORT.md's "Scoping decisions" for the full
reasoning.
"""

from __future__ import annotations

from collections.abc import Sequence

from plugins._shared.base import PluginResult

# A search term matching in the title counts for more than matching only in the body —
# titles are a stronger, human-authored relevance signal on every platform this searches.
_TITLE_MATCH_WEIGHT = 0.7
_BODY_MATCH_WEIGHT = 0.3


def score_result(result: PluginResult, terms: Sequence[str]) -> tuple[float, list[str]]:
    """Returns `(score, matched_terms)`. `score` is in `[0, 1]`: the weighted fraction of
    `terms` that appear in the result's title and/or body, where a title match counts for
    more than a body-only match. `matched_terms` (lowercased, deduplicated, sorted) becomes
    the result's `knowledge_items.tags` — see docs/knowledge-base/KNOWLEDGE_BASE.md's note on
    tags being the mechanism for cross-cutting, GIN-indexed queries.

    Deliberately platform-agnostic: uses only `PluginResult.title`/`.body`, fields every
    `Searchable` plugin returns regardless of platform — never a `platform_metadata` key,
    which is plugin-specific and opaque to this agent (see plugins/_shared/base.py).
    """
    cleaned_terms = [term.lower().strip() for term in terms if term.strip()]
    if not cleaned_terms:
        return 0.0, []

    title = (result.title or "").lower()
    body = (result.body or "").lower()

    matched: list[str] = []
    weight_total = 0.0
    for term in cleaned_terms:
        in_title = term in title
        in_body = term in body
        if in_title or in_body:
            matched.append(term)
        if in_title:
            weight_total += _TITLE_MATCH_WEIGHT
        elif in_body:
            weight_total += _BODY_MATCH_WEIGHT

    max_possible = len(cleaned_terms) * _TITLE_MATCH_WEIGHT
    score = min(1.0, weight_total / max_possible) if max_possible else 0.0
    return round(score, 2), sorted(set(matched))
