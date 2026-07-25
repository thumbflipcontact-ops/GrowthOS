"""Claude — the primary LLMProvider per ADR 0004. See
docs/decisions/0004-llm-provider-abstraction.md.

Thin wrapper around the `anthropic` SDK's async client. Claude's Messages API takes the
system prompt as a separate top-level parameter, not a message with `role="system"` — that's
a Claude-specific quirk this provider absorbs internally so `agents/content_agent/agent.py`
(and any future caller) only ever deals with the generic `LLMMessage`/role shape from
`app/core/llm/base.py`, never Claude's own request format.
"""

from __future__ import annotations

import anthropic
import httpx

from app.core.llm.base import CompletionRequest, CompletionResult, LLMProvider
from app.core.llm.errors import LLMRequestFailed


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        # `http_client` is test-only injection (an httpx.AsyncClient over
        # httpx.MockTransport, the same technique plugins/reddit and app/core/oauth/client.py
        # use) — the SDK itself builds its own real client when this is None. `max_retries`
        # is exposed (not just left at the SDK's own default) so a test asserting on a
        # failure path can set it to 0 and not wait through the SDK's own retry/backoff.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, http_client=http_client, max_retries=max_retries
        )

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        system_prompt = "\n\n".join(m.content for m in request.messages if m.role == "system")
        conversation = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role != "system"
        ]

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system_prompt or anthropic.Omit(),
                messages=conversation,  # type: ignore[arg-type]
            )
        except anthropic.AnthropicError as exc:
            raise LLMRequestFailed(f"Anthropic request failed: {exc}") from exc

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return CompletionResult(
            text=text,
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
        )
