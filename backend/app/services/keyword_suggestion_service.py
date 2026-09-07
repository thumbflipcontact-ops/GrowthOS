"""Derives Reddit-search keyword suggestions from a project's own website — the actual "enter
your URL, AI finds keywords" step of the product (one layer up from
plugins/reddit/README.md's "no login needed" discovery design). Suggestion only: this never
writes anything itself — the caller (the frontend's settings/agents page) shows the result for
the user to edit, then saves it through the ordinary
`PUT /projects/{project_id}/agent-configs/conversation_finder` path, exactly like a fully
manually-typed keyword list.
"""

from __future__ import annotations

import json
import re

import httpx

from app.core.errors import ValidationError
from app.core.llm.base import CompletionRequest, LLMMessage, LLMProvider

_HTTP_TIMEOUT_SECONDS = 10.0
_MAX_PAGE_CHARS = 20_000  # plenty for a homepage; keeps the LLM call small and cheap
_USER_AGENT = "GrowthOS-KeywordSuggestion/1.0 (+https://usethreadly.co)"

_SCRIPT_OR_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = """You suggest Reddit search keywords for a product, given its own website
text. Respond with only a JSON object: {"keywords": ["...", "..."]}. Suggest 5 to 10 short
keywords or phrases a potential customer would actually type in a Reddit post or comment when
describing the problem this product solves — not the product's own name or marketing jargon.
Never invent claims about the product beyond what the page text says."""


class KeywordSuggestionService:
    async def suggest(self, *, url: str, llm: LLMProvider) -> list[str]:
        text = await self._fetch_text(url)
        if not text:
            raise ValidationError("Could not read any text from that URL.", details={"url": url})

        request = CompletionRequest(
            messages=[
                LLMMessage(role="system", content=_SYSTEM_PROMPT),
                LLMMessage(role="user", content=text[:_MAX_PAGE_CHARS]),
            ],
            max_tokens=500,
            temperature=0.3,
        )
        completion = await llm.complete(request)
        return _parse_keywords(completion.text)

    async def _fetch_text(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                response = await client.get(url, headers={"User-Agent": _USER_AGENT})
        except httpx.HTTPError as exc:
            raise ValidationError(f"Could not reach {url}: {exc}", details={"url": url}) from exc

        if response.status_code >= 400:
            raise ValidationError(f"{url} returned {response.status_code}.", details={"url": url})

        return _strip_html(response.text)


def _strip_html(html: str) -> str:
    without_script_style = _SCRIPT_OR_STYLE_RE.sub(" ", html)
    without_tags = _TAG_RE.sub(" ", without_script_style)
    return _WHITESPACE_RE.sub(" ", without_tags).strip()


def _parse_keywords(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError:
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            raise ValidationError("The model did not return a parseable suggestion.") from None
        data = json.loads(match.group(0))

    keywords = data.get("keywords") if isinstance(data, dict) else None
    if not isinstance(keywords, list):
        raise ValidationError("The model's response had no keywords list.")
    return [str(k).strip() for k in keywords if str(k).strip()]


__all__ = ["KeywordSuggestionService"]
