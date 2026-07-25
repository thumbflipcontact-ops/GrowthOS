# ADR 0004: Claude primary, OpenAI secondary, behind one provider interface

**Status:** Accepted — 2026-07-24

## Context

The original stack preferences listed both Anthropic Claude and OpenAI without specifying
their respective roles. Agent code needs LLM access for extraction (structuring a discovered
conversation into a `knowledge_item`), classification (buying intent, relevance filtering),
and generation (drafting replies/articles in the project's brand voice) — these have
different quality/cost/latency trade-offs.

## Decision

Define one `LLMProvider` interface (`backend/app/core/llm/`) that both Anthropic and OpenAI
clients implement. **Claude is the primary provider** for reasoning-heavy, judgment-heavy, or
externally-visible-content generation (drafting replies, articles, buying-intent
classification) — the tasks where output quality most directly affects what a human sees in
the Approval Inbox. **OpenAI is wired in as a secondary provider**, available per-call for
cheaper/bulk work (embeddings for `knowledge_items.embedding`, high-volume first-pass
relevance filtering) and as a documented fallback path if Anthropic has an outage.

Agent code never imports a specific provider's SDK directly — it calls `ctx.llm.complete(...)`
or `ctx.llm.embed(...)`, and which provider actually serves that call is resolved by
per-agent, per-call-type configuration (`LLM_PRIMARY_PROVIDER` and finer-grained overrides,
see `docs/config/CONFIGURATION.md`), not by which SDK the agent's code happens to import.

## Consequences

**Positive:** provider outage or pricing changes are a configuration change, not a code
change across every agent. Cost optimization (routing cheap classification work to a less
expensive model/provider) is a per-call-type config decision, tunable without touching agent
logic. Embeddings use OpenAI's `text-embedding-3` family regardless of which provider handles
generation, since `docs/database/SCHEMA.md`'s `vector(1536)` dimension is chosen to match it.

**Accepted trade-off:** an abstraction layer over two SDKs with genuinely different feature
surfaces (tool-calling formats, streaming, structured output mechanisms) has real
implementation cost and cannot expose every provider-specific capability — the `LLMProvider`
interface will necessarily be a common subset, not the union, of what Claude and OpenAI each
support. Agent code that needs a provider-specific capability not covered by the shared
interface is a signal to extend the interface deliberately, not to bypass it with a direct
SDK import.
