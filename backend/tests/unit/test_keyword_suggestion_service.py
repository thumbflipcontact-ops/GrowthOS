"""See app/services/keyword_suggestion_service.py. Uses httpx's MockTransport for the page
fetch (same technique test_resend_client.py/test_oauth_client.py use) and a fake LLMProvider
for the completion call — no test ever makes a real network or LLM call.
"""

from __future__ import annotations

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

    keywords = await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)

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

    keywords = await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)

    assert keywords == ["a", "b"]


@pytest.mark.asyncio
async def test_suggest_raises_on_unreachable_url(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)


@pytest.mark.asyncio
async def test_suggest_raises_on_error_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)


@pytest.mark.asyncio
async def test_suggest_raises_on_empty_page_text(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<script>only script content</script>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM("{}")

    with pytest.raises(ValidationError):
        await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)


@pytest.mark.asyncio
async def test_suggest_raises_when_model_response_has_no_keywords_list(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>content</p>")

    _patch_transport(monkeypatch, handler)
    llm = _FakeLLM('{"not_keywords": []}')

    with pytest.raises(ValidationError):
        await KeywordSuggestionService().suggest(url="https://example.com", llm=llm)
