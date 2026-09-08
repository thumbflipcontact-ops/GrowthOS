"""See app/services/keyword_suggestion_service.py. Uses httpx's MockTransport for the page
fetch (same technique test_resend_client.py/test_oauth_client.py use) and a fake LLMProvider
for the completion call — no test ever makes a real network or LLM call.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.core.errors import ValidationError
from app.core.llm.base import CompletionRequest, CompletionResult
from app.services.keyword_suggestion_service import KeywordSuggestionService


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import app.services.keyword_suggestion_service as service_module

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(service_module.httpx, "AsyncClient", fake_async_client)


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.last_request: CompletionRequest | None = None

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.last_request = request
        return CompletionResult(text=self._text, model="fake")


class _FakeUsage:
    """Stands in for LlmUsageClient (app/services/llm_usage.py) — these tests care about
    keyword parsing, not cost logging, so this just needs to satisfy the call shape."""

    def __init__(self) -> None:
        self.recorded: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


async def _suggest(llm: _FakeLLM, *, url: str = "https://example.com") -> list[str]:
    return await KeywordSuggestionService().suggest(
        url=url, llm=llm, usage=_FakeUsage(), org_id=uuid.uuid4(), project_id=uuid.uuid4()  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_suggest_strips_html_and_returns_parsed_keywords(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><style>.x{}</style></head>"
            "<body><script>evil()</script><h1>Crawl Budget Tool</h1>"
            "<p>Fix technical SEO issues fast.</p></body></html>",
        )

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM('{"keywords": ["crawl budget", "technical seo", "site audit"]}')

    keywords = await _suggest(llm)

    assert keywords == ["crawl budget", "technical seo", "site audit"]
    assert llm.last_request is not None
    user_message = llm.last_request.messages[-1].content
    assert "evil()" not in user_message
    assert ".x{}" not in user_message
    assert "Crawl Budget Tool" in user_message


@pytest.mark.asyncio
async def test_suggest_extracts_json_object_from_surrounding_text(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>Some content</p>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM('Sure, here you go: {"keywords": ["a", "b"]} — hope that helps!')

    keywords = await _suggest(llm)

    assert keywords == ["a", "b"]


@pytest.mark.asyncio
async def test_suggest_raises_on_unreachable_url(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await _suggest(llm)


@pytest.mark.asyncio
async def test_suggest_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await _suggest(llm)


@pytest.mark.asyncio
async def test_suggest_raises_on_empty_page_text(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<script>only script content</script>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await _suggest(llm)


@pytest.mark.asyncio
async def test_suggest_raises_when_model_response_has_no_keywords_list(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>content</p>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM('{"not_keywords": []}')

    with pytest.raises(ValidationError):
        await _suggest(llm)


@pytest.mark.asyncio
async def test_suggest_drops_sentence_length_outliers(monkeypatch) -> None:
    # Real production incident: long, sentence-like keywords ("affordable way to promote my
    # website") reliably return zero Reddit search results even for a common topic — Reddit's
    # search requires every word to co-occur. The prompt asks for short keywords directly;
    # this is the defensive backstop for whenever the model doesn't fully comply.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>content</p>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM(
        '{"keywords": ["crawl budget", '
        '"looking for an affordable way to promote my website", '
        '"cheap hosting"]}'
    )

    keywords = await _suggest(llm)

    assert keywords == ["crawl budget", "cheap hosting"]


@pytest.mark.asyncio
async def test_suggest_falls_back_to_unfiltered_list_if_everything_is_long(monkeypatch) -> None:
    # Never return nothing just because every suggestion happened to be long — some result
    # beats silently empty keywords.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>content</p>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM('{"keywords": ["looking for an affordable way to promote my website"]}')

    keywords = await _suggest(llm)

    assert keywords == ["looking for an affordable way to promote my website"]
