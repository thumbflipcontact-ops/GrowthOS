# Scalability Considerations

**Version 2** — adds plugin count and event volume as explicit scaling dimensions, given the
100+ plugin requirement and the domain-event architecture introduced in the design review.

## What "scale" means for GrowthOS, at each phase

Scale is not a single axis here — five different growth dimensions stress the system
differently, and conflating them leads to solving the wrong problem early:

1. **Knowledge base volume** (rows in `knowledge_items`, growing continuously and
   permanently — nothing is ever deleted, see `docs/database/SCHEMA.md`).
2. **Number of projects per org** (Phase 3: multiple SaaS businesses run by one founder).
3. **Number of installed plugins** (up to 100+ over GrowthOS's lifetime — the explicit
   requirement behind the plugin architecture, `docs/plugins/PLUGIN_ARCHITECTURE.md`).
4. **Domain event volume and dispatch throughput** (new in V2 — every discovery, approval,
   and publish is now also an event row; see `ARCHITECTURE.md` §7).
5. **Number of orgs** (Phase 4 only, if GrowthOS is ever sold — see `ROADMAP.md`).

v1/Phase 1–3 only need to handle (1)–(4) well. Designing for (5) now, beyond the
tenant-ready schema already in place, would be solving a problem that doesn't exist yet.

## Plugin count

The plugin architecture (manifest discovery, segmented capability Protocols — see
`docs/plugins/PLUGIN_ARCHITECTURE.md`) is designed so *adding* a plugin doesn't cost more as
the count grows — no central list to edit, no per-plugin frontend code. What does grow
linearly with plugin count: the `PluginCatalog` startup scan (cheap — reading N manifests is
not a meaningful cost even at N=100+), the shared plugin contract test suite's CI runtime
(flagged in `docs/testing/TESTING.md` §7.2 as needing a selective/matrixed CI policy once this
becomes noticeable, not before), and per-plugin observability surface area
(`docs/observability/OBSERVABILITY.md` — this is *why* metrics/dashboards exist, not
optional polish, once "which of my 40 plugins needs attention" stops being answerable by
memory).

## Domain event volume

Every `knowledge_items`/`content_items` write and every webhook now also writes a
`domain_events` row (`ARCHITECTURE.md` §7). This table is append-only and retained
permanently by design (it's also a debuggable causality trail), so its growth is a strict
superset of `knowledge_items`' + `content_items`' growth — the same "will this matter" answer
applies (not for a long time at solo-founder scale) and the same mitigation applies if it
ever does (partition by `project_id` or by month; the partial `dispatched_at is null` index
already keeps the dispatcher's hot-path query cheap regardless of total table size — see
`docs/database/SCHEMA.md`). The dispatcher itself (an Arq periodic job) scales by shortening
its poll interval or, if fan-out breadth per event grows large, sharding subscriber dispatch
across more `worker-events` replicas — both config/replica-count changes, not redesigns.

## Knowledge base volume

This is the dimension most likely to actually matter within the first year, since the
system is designed to accumulate data forever. Mitigations already in the schema:
`pgvector` HNSW index for semantic search at scale (`docs/database/SCHEMA.md`), GIN index on
`tags`, `project_id` on every scoped index so query plans stay narrow as the table grows
across multiple projects. If/when a single project's `knowledge_items` table grows large
enough to matter (likely tens of millions of rows before this is a real concern, given the
per-day discovery volume one founder's agents will realistically produce), partitioning by
`project_id` or by month is a mechanical follow-up — not a redesign, since the access
patterns (always project-scoped, usually date-bounded) already align with a sane partition
key.

## Agent/job throughput

Background job load scales with (number of projects) × (number of enabled agents) ×
(schedule frequency + event volume). Arq worker pools for the `agent-runs`, `worker-events`,
and `worker-publish` queues each scale horizontally independently — add worker
containers/replicas per queue — since jobs are independent and stateless beyond their
database reads/writes (`docs/jobs/BACKGROUND_JOBS.md`). The realistic bottleneck at
solo-founder scale is external API rate limits (per-plugin, see
`docs/plugins/PLUGIN_ARCHITECTURE.md`), not compute — adding more workers doesn't help once
Reddit's rate limit is the constraint, so capacity planning here means monitoring
plugin-level throttling (`docs/observability/OBSERVABILITY.md`), not just worker CPU.

## Redis contention

Redis backs three distinct uses — the Arq broker (job execution *and*, since V2, event
dispatch), the application cache, and per-plugin rate-limit token buckets. Fine as one
instance at v1 scale; worth a monitoring note (which of the three uses is contending) before
it becomes a debugging mystery, and the first thing to split into a dedicated instance if
event-dispatch latency ever gets noisy under load from the other two uses.

## Database

Postgres vertical scaling (bigger instance) covers Phase 1–3 comfortably. Read replicas are a
natural next step if the dashboard's read load (Knowledge Base Explorer, Daily Brief views)
ever contends meaningfully with write load from agent runs — not needed until there's
evidence of that contention, per general practice of not scaling ahead of measured need.

## LLM cost and latency

Cost scales with agent run frequency × project count × LLM calls per run. The
provider-abstraction layer (`docs/decisions/0004-llm-provider-abstraction.md`) exists partly
for this reason: bulk/cheap classification work (e.g. `conversation_finder`'s initial
relevance filtering) can route to a cheaper model or provider than judgment-heavy drafting
work (`content_agent`), without changing calling code — a per-agent, per-call-type model
selection is config, not a rewrite.

## Multi-project isolation under load

A noisy/expensive project (e.g. one running very frequent schedules, or generating a large
share of domain events) should not starve another project's agent runs or event dispatch. The
`agent-runs` and event-dispatch queues are currently single shared queues across projects for
v1 simplicity; if this becomes a real problem (Phase 3, multiple active projects), fair
scheduling (per-project sub-queues or weighted job priority) is the fix — not a v1 concern,
flagged here so it isn't forgotten when Phase 3 starts.

## What's explicitly not being optimized for yet

- Concurrent-tenant load at real SaaS scale (thousands of orgs) — Phase 4 territory, and a
  meaningfully different set of problems (noisy-neighbor isolation, per-tenant rate limiting,
  billing-aware throttling) than anything in this document.
- Global/multi-region deployment — single-region is correct until there's a concrete latency
  or compliance reason otherwise.
