-- GrowthOS core schema — Version 2
-- This is the design source of truth referenced by docs/database/SCHEMA.md and
-- docs/database/ERD.md. Actual migrations (Alembic) in backend/migrations/ are generated
-- from this design, not the other way around — when the schema changes, update this file
-- first, then generate the migration.
--
-- Conventions:
--   * every table has a UUID primary key `id`, generated client-side or via gen_random_uuid()
--   * every tenant-scoped table carries project_id (which transitively implies org_id —
--     see docs/database/SCHEMA.md for why we don't duplicate organization_id everywhere)
--   * every table has created_at; mutable tables also have updated_at
--   * soft deletes are NOT used — see docs/decisions/0001-multi-tenancy.md and
--     docs/database/SCHEMA.md for the reasoning; use status/archived flags instead
--   * a native Postgres ENUM is used only for CORE-OWNED, closed taxonomies (buying_intent,
--     plugin_capability — GrowthOS itself defines the full set of valid values). Anything a
--     PLUGIN PACKAGE contributes values for (content_items.type) is `text`, validated at the
--     application layer against the currently-installed plugin catalog — never a database
--     enum. See docs/decisions/0008-plugin-contributed-content-types.md for why this
--     distinction matters and where the line is drawn.

-- gen_random_uuid() is a Postgres core builtin since v13 — no pgcrypto extension needed.
-- (Discovered during Phase 1 implementation: some minimal Postgres distributions don't
-- bundle pgcrypto at all, and requiring it was already unnecessary on our targeted PG16.
-- This is a DDL correctness fix, not an architectural change — nothing in ARCHITECTURE.md
-- or LOCKED_DECISIONS.md specifies pgcrypto.)
create extension if not exists "vector";     -- pgvector, for knowledge_items.embedding

-- ============================================================================
-- Identity & tenancy
-- ============================================================================

create table organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text not null unique,
    created_at  timestamptz not null default now()
);

create table users (
    id              uuid primary key default gen_random_uuid(),
    email           text not null unique,
    name            text not null,
    password_hash   text not null,
    created_at      timestamptz not null default now()
);

create type membership_role as enum ('owner', 'member');

create table memberships (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references organizations(id) on delete cascade,
    user_id     uuid not null references users(id) on delete cascade,
    role        membership_role not null default 'owner',
    created_at  timestamptz not null default now(),
    unique (org_id, user_id)
);

create type project_status as enum ('active', 'paused', 'archived');

create table projects (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references organizations(id) on delete cascade,
    name            text not null,
    slug            text not null,
    icp_config      jsonb not null default '{}',   -- ideal customer profile definition
    brand_voice     jsonb not null default '{}',   -- tone/style guide agents draft against
    status          project_status not null default 'active',
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (org_id, slug)
);

-- ============================================================================
-- Plugin catalog, connections & agents (configuration + execution audit trail)
-- ============================================================================

-- Core-owned, closed taxonomy of capability KINDS — the four capability Protocols defined
-- in docs/plugins/PLUGIN_ARCHITECTURE.md. A plugin doesn't invent new capability kinds, it
-- only implements a subset of these fixed four, so (unlike content type) this is a correct
-- use of a native enum. See docs/database/SCHEMA.md.
create type plugin_capability as enum ('searchable', 'publishable', 'webhook_receivable', 'metrics_queryable');
-- 'expired' (added alongside the OAuth2 framework, see docs/auth/OAUTH2_ARCHITECTURE.md §2
-- and docs/decisions/0011-generic-oauth2-plugin-framework.md) is distinct from 'error': a
-- permanent refresh failure (refresh token itself revoked/expired) needs a human to
-- reconnect; a transient failure stays 'connected' and is retried, never surfaced as
-- 'expired'.
create type plugin_connection_status as enum ('connected', 'error', 'disconnected', 'expired');

-- Mirrors the in-process plugin manifest scan (docs/plugins/PLUGIN_ARCHITECTURE.md
-- §Discovery) performed at startup — refreshed on every process start, not hand-edited.
-- Exists so the API/frontend can query "what plugins exist and what do they need" without
-- importing plugin Python code into a request path.
create table plugin_catalog (
    plugin_key          text primary key,   -- matches plugins/<plugin_key>/
    interface_version   text not null,
    capabilities        plugin_capability[] not null default '{}',
    content_types       jsonb not null default '[]',  -- mirrors each plugin's ContentTypeSpec list
    config_schema       jsonb not null,                -- JSON Schema, generated from the plugin's pydantic model
    auth_type           text not null,
    refreshed_at        timestamptz not null default now()
);

create table plugin_connections (
    id                      uuid primary key default gen_random_uuid(),
    project_id              uuid not null references projects(id) on delete cascade,
    plugin_key              text not null,   -- matches plugin_catalog.plugin_key; validated at the
                                              -- application layer against the currently-installed
                                              -- catalog, not a hard FK, since the catalog is rebuilt
                                              -- at each process start (see docs/database/SCHEMA.md)
    label                   text not null default 'default',  -- disambiguates multiple connections
                                                                -- to the SAME plugin within one project
                                                                -- (two Reddit accounts, two Slack
                                                                -- workspaces) — see
                                                                -- docs/auth/OAUTH2_ARCHITECTURE.md §2
    capabilities_enabled    plugin_capability[] not null default '{}',   -- data-level gate — see
                                                                          -- docs/plugins/PLUGIN_ARCHITECTURE.md
                                                                          -- "two independent gates"
    config                  jsonb not null default '{}',   -- plugin-specific settings (subreddit
                                                             -- allowlist, OAuth scopes, ...),
                                                             -- validated against plugin_catalog.config_schema
    credentials_encrypted   bytea,           -- envelope-encrypted at the application layer,
                                              -- see docs/security/SECURITY.md and
                                              -- docs/decisions/0010-envelope-encryption-for-credentials.md
                                              -- {"access_token", "refresh_token", "token_type"} for
                                              -- auth_type="oauth2" — see docs/auth/OAUTH2_ARCHITECTURE.md
    credential_data_key_wrapped  bytea,      -- the per-connection data key, wrapped by the current
                                              -- master key — see docs/security/SECURITY.md
    status                  plugin_connection_status not null default 'disconnected',
    last_checked_at         timestamptz,
    -- Plaintext, deliberately — neither is a credential. See
    -- docs/auth/OAUTH2_ARCHITECTURE.md §2 for why these live outside the encrypted envelope.
    token_expires_at        timestamptz,      -- drives the OAuth refresh sweep's query; null for
                                               -- non-OAuth auth_types
    granted_scopes          text[] not null default '{}',  -- what was actually authorized, which may
                                                             -- differ from the manifest's requested scopes
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    unique (project_id, plugin_key, label)
);

-- Hot-path index for the OAuth token-refresh sweep (app/jobs/oauth_refresh.py) — same
-- partial-index pattern as idx_domain_events_undispatched below.
create index idx_plugin_connections_oauth_refresh on plugin_connections (token_expires_at)
    where token_expires_at is not null and status = 'connected';

create table agent_configs (
    id              uuid primary key default gen_random_uuid(),
    project_id      uuid not null references projects(id) on delete cascade,
    agent_key       text not null,   -- matches agents/<agent_key>/
    schedule_cron   text,            -- null = on-demand only, no schedule
    config          jsonb not null default '{}',
    enabled         boolean not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (project_id, agent_key)
);

create type agent_run_status as enum ('queued', 'running', 'succeeded', 'failed');

create table agent_runs (
    id                  uuid primary key default gen_random_uuid(),
    agent_config_id     uuid not null references agent_configs(id) on delete cascade,
    project_id          uuid not null references projects(id) on delete cascade,
    agent_key           text not null,
    status              agent_run_status not null default 'queued',
    started_at          timestamptz,
    finished_at         timestamptz,
    summary             jsonb,        -- structured run output, surfaced in the Morning Brief
    error               text,
    created_at          timestamptz not null default now()
);

-- ============================================================================
-- Domain events — the transactional outbox agents communicate through
-- (see ARCHITECTURE.md §7, docs/decisions/0006-event-driven-agent-communication.md)
-- ============================================================================

-- Every row here is written in the SAME transaction as the row that caused it (e.g. a
-- knowledge_items insert and its knowledge_item.created event commit together) — this is
-- the property that makes the outbox reliable. Never insert an event outside the
-- transaction of the fact it describes.
create table domain_events (
    id              uuid primary key default gen_random_uuid(),
    project_id      uuid not null references projects(id) on delete cascade,
    event_type      text not null,          -- 'knowledge_item.created', 'content_item.approved', ...
    payload         jsonb not null,          -- event-specific data; always includes the source row id
    occurred_at     timestamptz not null default now(),
    dispatched_at   timestamptz              -- null until fan-out has been attempted at least once
);

-- The dispatcher's hot-path query: "give me undispatched events." Partial index keeps this
-- cheap regardless of how large the (permanently retained) full table grows.
create index idx_domain_events_undispatched on domain_events (project_id) where dispatched_at is null;
create index idx_domain_events_project_type on domain_events (project_id, event_type);

-- ============================================================================
-- Knowledge base — the institutional memory
-- ============================================================================

create type buying_intent as enum ('none', 'low', 'medium', 'high');

create table knowledge_items (
    id                      uuid primary key default gen_random_uuid(),
    project_id              uuid not null references projects(id) on delete cascade,
    source_agent_run_id     uuid references agent_runs(id) on delete set null,
    platform                text not null,       -- 'reddit', 'linkedin', 'gsc_community', ...
    url                     text not null,
    discovered_at           timestamptz not null default now(),
    -- title/body_excerpt: the discovered post's own title and a capped excerpt of its body,
    -- captured verbatim at discovery time (Conversation Finder, Phase 2A) so a later agent
    -- (Content Agent, Phase 2B) has grounding text to draft and cite from without re-fetching
    -- the platform. Added alongside Phase 2B, not Phase 2A: no consumer needed them until
    -- Content Agent did. Both null for any row discovered before this column existed.
    title                   text,
    body_excerpt            text,
    problem                 text,
    industry                text,
    product                 text,
    pain_point              text,
    buying_intent           buying_intent not null default 'none',
    suggested_reply         text,
    suggested_article       text,
    suggested_product_idea  text,
    tags                    text[] not null default '{}',
    confidence              numeric(3,2) not null default 0.0 check (confidence between 0 and 1),
    outcome                 text,                -- filled in later by an enrichment job
    -- Opaque, plugin-specific passthrough of PluginResult.platform_metadata (Reddit's
    -- subreddit/thing_id/score/num_comments, ...) — see plugins/_shared/base.py. Core schema
    -- and Conversation Finder never interpret this; it exists so a platform-aware consumer
    -- (e.g. Content Agent choosing what to set content_items.target_ref to) has the plugin's
    -- own reference available without a second fetch. Added alongside title/body_excerpt,
    -- same reasoning.
    platform_metadata       jsonb not null default '{}',
    embedding               vector(1536),         -- for semantic search over the knowledge base
    created_at              timestamptz not null default now(),
    unique (project_id, url)
);

create index idx_knowledge_items_project on knowledge_items (project_id);
create index idx_knowledge_items_tags on knowledge_items using gin (tags);
create index idx_knowledge_items_embedding on knowledge_items using hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- Content items — the human-approval gate (see ARCHITECTURE.md §8)
-- ============================================================================

create type content_item_status as enum (
    'draft', 'pending_review', 'approved', 'rejected', 'published'
);

create table content_items (
    id                      uuid primary key default gen_random_uuid(),
    project_id              uuid not null references projects(id) on delete cascade,
    -- `type` is TEXT, not a native enum: the set of valid content types is contributed by
    -- plugin manifests (plugin_catalog.content_types), not owned by core schema. Validated
    -- at the application layer in ContentApprovalService against the currently-installed
    -- plugin catalog. See docs/decisions/0008-plugin-contributed-content-types.md — this is
    -- the direct fix for the V1 finding that a closed DB enum here would force a schema
    -- migration for every plugin introducing a new publishable content shape.
    type                    text not null,
    status                  content_item_status not null default 'draft',
    body                    text not null,
    target_platform         text,        -- plugin_key this will publish through
    target_ref              text,        -- e.g. the Reddit thread ID being replied to
    knowledge_item_id       uuid references knowledge_items(id) on delete set null,
    created_by_agent_run_id uuid references agent_runs(id) on delete set null,
    reviewed_by_user_id     uuid references users(id) on delete set null,
    reviewed_at             timestamptz,
    published_at            timestamptz,
    publish_error           text,
    -- confidence/reasoning/evidence: the drafting agent's own self-assessment, added
    -- alongside Content Agent (Phase 2B, see agents/content_agent/README.md) — no consumer
    -- needed these until an agent actually drafted content. `confidence` mirrors
    -- knowledge_items.confidence's shape (a 0-1 score, meaning here "how good the agent
    -- judges its own draft to be," not a platform-search-relevance score). `evidence` is a
    -- JSON array of short quotes/citations from the source knowledge_item the draft is
    -- grounded in — never free-form prose, so a human reviewer (Phase 2C) can scan it
    -- quickly.
    confidence              numeric(3,2) not null default 0.0 check (confidence between 0 and 1),
    reasoning               text,
    evidence                jsonb not null default '[]',
    -- Optimistic concurrency guard on the approve/reject transition (design review
    -- §3.2 / LOCKED_DECISIONS L12) — ContentApprovalService's update includes
    -- `where version = :expected_version`, incrementing it on every transition. A racing
    -- second approve/reject reads a stale version, affects zero rows, and the service
    -- layer surfaces that as the documented 409 in docs/api/API_DESIGN.md, instead of a
    -- silent double-transition.
    version                 integer not null default 1,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),

    -- reviewed_at / reviewed_by_user_id must both be set or both be null — enforced here
    -- as well as in ContentApprovalService, because this invariant is cheap to guarantee
    -- at the database level and too important to rely on application code alone for.
    constraint review_fields_consistent check (
        (reviewed_by_user_id is null) = (reviewed_at is null)
    )
);

create index idx_content_items_project_status on content_items (project_id, status);

-- ============================================================================
-- Security audit trail (see docs/security/SECURITY.md, design review §5.3)
-- ============================================================================

-- Separate from content_items' review trail deliberately: that table proves a human
-- approved a specific piece of content; this one reconstructs what happened to an account
-- during a security incident (login, plugin connect/disconnect, credential rotation).
-- Different purpose, different retention/query patterns — not worth conflating.
create table audit_log (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references organizations(id) on delete cascade,
    actor_user_id   uuid references users(id) on delete set null,
    action          text not null,      -- 'login', 'plugin.connected', 'credential.rotated', ...
    target          text,               -- free-form reference to what was acted on
    metadata        jsonb not null default '{}',
    created_at      timestamptz not null default now()
);

create index idx_audit_log_org_created on audit_log (org_id, created_at desc);

-- ============================================================================
-- CRM-lite: companies, contacts, competitors
-- ============================================================================

create table companies (
    id          uuid primary key default gen_random_uuid(),
    project_id  uuid not null references projects(id) on delete cascade,
    name        text not null,
    domain      text,
    industry    text,
    size_bucket text,
    icp_score   numeric(3,2) check (icp_score between 0 and 1),
    source      text,        -- which agent/plugin surfaced this company
    created_at  timestamptz not null default now(),
    unique (project_id, domain)
);

create type contact_status as enum ('new', 'contacted', 'replied', 'qualified', 'customer', 'lost');

create table contacts (
    id          uuid primary key default gen_random_uuid(),
    project_id  uuid not null references projects(id) on delete cascade,
    company_id  uuid references companies(id) on delete set null,
    name        text,
    platform    text,
    profile_url text,
    role        text,
    status      contact_status not null default 'new',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table competitors (
    id          uuid primary key default gen_random_uuid(),
    project_id  uuid not null references projects(id) on delete cascade,
    name        text not null,
    domain      text,
    notes       text,
    created_at  timestamptz not null default now(),
    unique (project_id, domain)
);

create table competitor_observations (
    id              uuid primary key default gen_random_uuid(),
    competitor_id   uuid not null references competitors(id) on delete cascade,
    observed_at     timestamptz not null default now(),
    type            text not null,     -- 'pricing_change', 'new_feature', 'content_published', ...
    summary         text not null,
    source_url      text,
    created_at      timestamptz not null default now()
);

-- ============================================================================
-- Daily brief — the materialized "what should I do today" view
-- ============================================================================

create table daily_briefs (
    id          uuid primary key default gen_random_uuid(),
    project_id  uuid not null references projects(id) on delete cascade,
    brief_date  date not null,
    summary     jsonb not null,   -- assembled from the day's agent_runs; shape documented
                                    -- in docs/knowledge-base/KNOWLEDGE_BASE.md
    created_at  timestamptz not null default now(),
    unique (project_id, brief_date)
);
