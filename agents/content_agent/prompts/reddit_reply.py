"""Prompt template + response contract for drafting a Reddit reply. See
agents/content_agent/README.md and docs/reviews/CONTENT_AGENT_IMPLEMENTATION_REPORT.md.

Deliberately asks for a JSON response and parses it here, rather than using a
provider-specific structured-output/tool-calling mechanism — `app/core/llm/base.py`'s
`LLMProvider` interface is a plain-text completion API (ADR 0004's "common subset, not the
union" trade-off), so structured output is this agent's own concern, not the platform's.

Versioned by replacing this file's constants, not by editing prompt text inline elsewhere —
see docs/agents/AGENT_ARCHITECTURE.md's anatomy note on `prompts/`.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

# Version 1. Bump this comment (and consider a reddit_reply_v2.py alongside it, not a silent
# in-place rewrite) if the response contract below changes in a way that would invalidate
# how existing drafts are interpreted.
SYSTEM_PROMPT = """\
You are the Content Agent for GrowthOS, a tool that helps a solo SaaS founder engage \
authentically in online discussions about problems their product solves.

Your job: draft ONE reply to a specific Reddit post, for a human to review and approve \
before anything is posted. You never post anything yourself.

Rules:
- Be genuinely helpful and specific to the post's content. Never generic, never salesy.
- Do not pretend to be a customer or fabricate experience. Do not mention the founder's \
product or company unless the post is directly asking for tool/product recommendations.
- Keep the reply within the platform's length limit given below.
- Your `evidence` must be short, near-verbatim quotes copied from the post's title/body \
given to you -- never invented, never paraphrased into a "quote."
- Your `confidence` is your own honest estimate (0 to 1) of how good and appropriate this \
reply is -- not how relevant the post was to search for.

Respond with ONLY a single JSON object, no other text, matching exactly this shape:
{"reply": "...", "confidence": 0.0, "reasoning": "...", "evidence": ["...", "..."]}
"""


class DraftReplyExtraction(BaseModel):
    reply: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[str] = Field(default_factory=list)


class DraftParsingError(Exception):
    """The model's response text could not be parsed into a `DraftReplyExtraction` — see
    `parse_draft_reply`. A soft failure: the caller (agents/content_agent/agent.py) records
    it in `AgentResult.errors` and creates no `content_items` row, rather than raising and
    triggering an Arq retry that would likely reproduce the same malformed response."""


def build_user_prompt(
    *,
    subreddit: str | None,
    title: str | None,
    body_excerpt: str | None,
    tags: list[str],
    brand_voice: dict,
    max_reply_length: int,
) -> str:
    lines = ["A Reddit post to reply to:", ""]
    if subreddit:
        lines.append(f"Subreddit: r/{subreddit}")
    lines.append(f"Title: {title or '(no title)'}")
    lines.append(f"Body: {body_excerpt or '(no body text captured)'}")
    if tags:
        lines.append(f"Matched topics: {', '.join(tags)}")
    lines.append("")
    lines.append(f"Maximum reply length: {max_reply_length} characters.")
    if brand_voice:
        lines.append("")
        lines.append(f"Brand voice guidance: {json.dumps(brand_voice)}")
    return "\n".join(lines)


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_draft_reply(text: str) -> DraftReplyExtraction:
    """Parses the model's response text as a `DraftReplyExtraction`. Tries the raw text
    first; if the model wrapped the JSON in markdown fences or added surrounding prose
    despite the system prompt's instruction, falls back to extracting the first `{...}`
    block before giving up. Raises `DraftParsingError` (never propagates the underlying
    `pydantic`/`json` exception) so the caller has one exception type to catch."""
    try:
        return DraftReplyExtraction.model_validate_json(text)
    except (ValidationError, ValueError):
        pass

    match = _JSON_OBJECT_RE.search(text)
    if match is not None:
        try:
            return DraftReplyExtraction.model_validate_json(match.group(0))
        except (ValidationError, ValueError):
            pass

    raise DraftParsingError(f"Could not parse a draft reply from the model's response: {text!r}")
