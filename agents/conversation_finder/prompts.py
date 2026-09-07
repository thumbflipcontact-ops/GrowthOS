"""LLM-based lead scoring — see README.md and agents/conversation_finder/agent.py's run().
Mirrors agents/content_agent/prompts/_shared.py's exact contract shape (a BaseModel response
contract + a dedicated parsing exception that never propagates a raw pydantic/json error),
just scoring a *batch* of candidates in one call instead of drafting one reply — the first
batched LLM call in this codebase, deliberate given how many raw results a single
Conversation Finder run can produce (see ConversationFinderConfig.max_results_per_platform).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from plugins._shared.base import PluginResult

# A capped excerpt per candidate, not the full body — keeps the batched prompt's size
# bounded regardless of how verbose an individual post is. Independent of
# agent.py's own _BODY_EXCERPT_MAX_CHARS (what gets persisted) — this is what gets shown to
# the model, and doesn't need to be as generous.
_PROMPT_BODY_EXCERPT_CHARS = 800

BuyingIntentLiteral = Literal["none", "low", "medium", "high"]


class LeadScore(BaseModel):
    # Echoed back by the model, not inferred from response order — see parse_lead_scores's
    # docstring for why matching by url is safer than trusting array order/count survives
    # the round trip intact.
    url: str
    relevance: float = Field(ge=0.0, le=1.0)
    buying_intent: BuyingIntentLiteral
    reasoning: str


class LeadScoreBatch(BaseModel):
    scores: list[LeadScore]


class LeadScoreParsingError(Exception):
    """The model's response text could not be parsed into a `LeadScoreBatch` — see
    `parse_lead_scores`. A soft failure: the caller (agents/conversation_finder/agent.py)
    falls every candidate in this batch back to the deterministic keyword score rather than
    raising and failing the whole discovery run over one malformed response."""


_JSON_ARRAY_OR_OBJECT_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)

SYSTEM_PROMPT = """You judge whether Reddit posts are worth a business replying to, given
what that business is looking for. Respond with only a JSON object:
{"scores": [{"url": "...", "relevance": 0.0, "buying_intent": "none", "reasoning": "..."}]}
— exactly one entry per post given to you, in any order, each echoing that post's own url
back exactly as given.

relevance (0.0-1.0): does this post genuinely relate to what the business is looking for —
not just share a word in common with it. A post using the same words for something
unrelated should score near 0.0.

buying_intent: "high" if the poster is actively looking for a solution to this need right
now; "medium" if they're discussing the problem without clearly seeking a solution; "low" if
only tangentially related; "none" if not relevant at all.

reasoning: one short sentence explaining the score, written for a person deciding whether to
reply to this post — not a restatement of the post's own content.

Never invent claims about a post beyond what its text says."""


def build_user_prompt(
    *,
    candidates: list[PluginResult],
    project_name: str,
    keywords: list[str],
    brand_voice: dict,
) -> str:
    lines = [
        f'A business named "{project_name}" is looking for Reddit posts related to: '
        f"{', '.join(keywords)}."
    ]
    if brand_voice:
        lines.append(f"Additional context about the business: {json.dumps(brand_voice)}")
    lines.append(f"\nScore each of the following {len(candidates)} posts:\n")

    for i, candidate in enumerate(candidates, start=1):
        title = candidate.title or "(no title)"
        body = (candidate.body or "")[:_PROMPT_BODY_EXCERPT_CHARS]
        lines.append(f"{i}. url: {candidate.url}\ntitle: {title}\nbody: {body}\n")

    return "\n".join(lines)


def parse_lead_scores(text: str) -> list[LeadScore]:
    """Parses the model's response text into a list of `LeadScore`. Tries the raw text
    first; if the model wrapped the JSON in markdown fences or added surrounding prose
    despite the system prompt's instruction, falls back to extracting the first
    `{...}`/`[...]` block before giving up. Raises `LeadScoreParsingError` (never propagates
    the underlying `pydantic`/`json` exception) so the caller has one exception type to
    catch. Matching results back to candidates by `LeadScore.url` (not position) is the
    caller's job — this only parses, it doesn't know what was asked for."""
    for candidate_text in _candidate_texts(text):
        # Try the documented shape first: {"scores": [...]}.
        try:
            return LeadScoreBatch.model_validate_json(candidate_text).scores
        except (ValidationError, ValueError):
            pass
        # Fall back to a bare [...] array, in case the model dropped the wrapping object.
        try:
            raw = json.loads(candidate_text)
            if isinstance(raw, list):
                return [LeadScore.model_validate(item) for item in raw]
        except (ValidationError, ValueError, TypeError):
            pass

    raise LeadScoreParsingError(f"Could not parse lead scores from the model's response: {text!r}")


def _candidate_texts(text: str):
    yield text
    match = _JSON_ARRAY_OR_OBJECT_RE.search(text)
    if match is not None:
        yield match.group(0)


__all__ = [
    "LeadScore",
    "LeadScoreBatch",
    "LeadScoreParsingError",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "parse_lead_scores",
]
