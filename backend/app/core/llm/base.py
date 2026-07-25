"""The generic LLM provider interface — see docs/decisions/0004-llm-provider-abstraction.md.

Agent code never imports a specific provider's SDK directly — it calls
`ctx.llm.complete(...)`, and which provider actually serves that call is resolved by
`app/core/llm/factory.py` from `Settings.llm_primary_provider`, not by which SDK an agent's
code happens to import. This interface is deliberately a common subset, not the union, of
what Claude and OpenAI each support (ADR 0004's accepted trade-off) — no tool-calling,
streaming, or provider-specific structured-output mechanism is exposed here. An agent that
needs structured output asks for it in its prompt and parses the resulting text itself (see
`agents/content_agent/agent.py`), rather than this interface growing a provider-specific
mechanism for it.

`embed()` (mentioned in ADR 0004 for `knowledge_items.embedding`) is deliberately not part of
this Protocol yet — no provider implementation needs it until OpenAI/embeddings work is
actually in scope. Add it here, additively, when that's true; don't declare a method nothing
implements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(slots=True)
class CompletionRequest:
    messages: list[LLMMessage]
    max_tokens: int = 1024
    temperature: float = 0.7


@dataclass(slots=True)
class CompletionResult:
    text: str
    model: str
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
