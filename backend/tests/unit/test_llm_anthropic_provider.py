"""Unit tests for AnthropicProvider — see app/core/llm/anthropic_provider.py. Uses
httpx.MockTransport (not a live network call), the same technique
backend/tests/unit/test_oauth_client.py uses for OAuthClient.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.llm.anthropic_provider import AnthropicProvider
from app.core.llm.base import CompletionRequest, LLMMessage
from app.core.llm.errors import LLMRequestFailed


def _message_response(
    *, text_blocks: list[str] | None = None, model: str = "claude-sonnet-4-5"
) -> dict:
    blocks = text_blocks if text_blocks is not None else ["hello world"]
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": block} for block in blocks],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _provider(handler, *, max_retries: int = 2) -> AnthropicProvider:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-4-5",
        http_client=http_client,
        max_retries=max_retries,
    )


@pytest.mark.asyncio
async def test_complete_sends_system_and_user_messages_correctly() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_message_response())

    provider = _provider(handler)
    request = CompletionRequest(
        messages=[
            LLMMessage(role="system", content="You are a helpful assistant."),
            LLMMessage(role="user", content="Draft a reply."),
        ],
        max_tokens=500,
        temperature=0.3,
    )
    await provider.complete(request)

    assert captured["body"]["system"] == "You are a helpful assistant."
    assert captured["body"]["messages"] == [{"role": "user", "content": "Draft a reply."}]
    assert captured["body"]["max_tokens"] == 500
    assert captured["body"]["temperature"] == 0.3
    assert captured["body"]["model"] == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_complete_omits_system_param_when_no_system_message() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_message_response())

    provider = _provider(handler)
    await provider.complete(CompletionRequest(messages=[LLMMessage(role="user", content="hi")]))

    assert "system" not in captured["body"]


@pytest.mark.asyncio
async def test_complete_joins_multiple_system_messages() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_message_response())

    provider = _provider(handler)
    await provider.complete(
        CompletionRequest(
            messages=[
                LLMMessage(role="system", content="Part one."),
                LLMMessage(role="system", content="Part two."),
                LLMMessage(role="user", content="hi"),
            ]
        )
    )

    assert captured["body"]["system"] == "Part one.\n\nPart two."


@pytest.mark.asyncio
async def test_complete_extracts_text_and_metadata_from_the_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_message_response(model="claude-sonnet-4-5"))

    provider = _provider(handler)
    result = await provider.complete(
        CompletionRequest(messages=[LLMMessage(role="user", content="hi")])
    )

    assert result.text == "hello world"
    assert result.model == "claude-sonnet-4-5"
    assert result.stop_reason == "end_turn"
    assert result.input_tokens == 10
    assert result.output_tokens == 5


@pytest.mark.asyncio
async def test_complete_joins_multiple_text_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_message_response(text_blocks=["Hello, ", "world."]))

    provider = _provider(handler)
    result = await provider.complete(
        CompletionRequest(messages=[LLMMessage(role="user", content="hi")])
    )

    assert result.text == "Hello, world."


@pytest.mark.asyncio
async def test_complete_wraps_a_non_2xx_response_as_llm_request_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
        )

    provider = _provider(handler, max_retries=0)
    with pytest.raises(LLMRequestFailed):
        await provider.complete(CompletionRequest(messages=[LLMMessage(role="user", content="hi")]))


@pytest.mark.asyncio
async def test_complete_wraps_a_connection_error_as_llm_request_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("could not connect")

    provider = _provider(handler, max_retries=0)
    with pytest.raises(LLMRequestFailed):
        await provider.complete(CompletionRequest(messages=[LLMMessage(role="user", content="hi")]))
