# Entity Relationship Diagram

Mirrors [`database/schema.sql`](../../database/schema.sql) exactly. If this diagram and the
DDL ever disagree, the DDL wins — update this file.

**Version 2** — adds `plugin_catalog`, `domain_events`, and `audit_log`; `content_items.type`
is now `text` (not a native enum, so it's not shown as `enum` below); `plugin_connections`
gains `config` and the envelope-encryption columns; `content_items` gains `version`.

**OAuth2 framework** (ADR 0011, `docs/auth/OAUTH2_ARCHITECTURE.md`) — `plugin_connections`
gains `label` (multiple connections per plugin per project), `token_expires_at` and
`granted_scopes` (plaintext), and `plugin_connection_status` gains the `expired` value.
Relationships below are unchanged — this is additive columns on an existing entity, not a new
one.

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ MEMBERSHIPS : has
    USERS ||--o{ MEMBERSHIPS : has
    ORGANIZATIONS ||--o{ PROJECTS : owns
    ORGANIZATIONS ||--o{ AUDIT_LOG : has

    PROJECTS ||--o{ PLUGIN_CONNECTIONS : has
    PROJECTS ||--o{ AGENT_CONFIGS : has
    PROJECTS ||--o{ AGENT_RUNS : has
    PROJECTS ||--o{ DOMAIN_EVENTS : has
    PROJECTS ||--o{ KNOWLEDGE_ITEMS : has
    PROJECTS ||--o{ CONTENT_ITEMS : has
    PROJECTS ||--o{ COMPANIES : has
    PROJECTS ||--o{ CONTACTS : has
    PROJECTS ||--o{ COMPETITORS : has
    PROJECTS ||--o{ DAILY_BRIEFS : has

    PLUGIN_CATALOG ||--o{ PLUGIN_CONNECTIONS : "describes (app-layer validated, not FK)"

    AGENT_CONFIGS ||--o{ AGENT_RUNS : produces
    AGENT_RUNS ||--o{ KNOWLEDGE_ITEMS : discovers
    AGENT_RUNS ||--o{ CONTENT_ITEMS : drafts

    KNOWLEDGE_ITEMS ||--o{ DOMAIN_EVENTS : "publishes knowledge_item.created (same txn)"
    CONTENT_ITEMS ||--o{ DOMAIN_EVENTS : "publishes content_item.* (same txn)"

    KNOWLEDGE_ITEMS ||--o{ CONTENT_ITEMS : "informs (optional)"
    USERS ||--o{ CONTENT_ITEMS : reviews
    USERS ||--o{ AUDIT_LOG : acts

    COMPANIES ||--o{ CONTACTS : employs
    COMPETITORS ||--o{ COMPETITOR_OBSERVATIONS : "observed via"

    ORGANIZATIONS {
        uuid id PK
        text name
        text slug
    }
    USERS {
        uuid id PK
        text email
        text name
    }
    MEMBERSHIPS {
        uuid id PK
        uuid org_id FK
        uuid user_id FK
        enum role
    }
    PROJECTS {
        uuid id PK
        uuid org_id FK
        text name
        text slug
        jsonb icp_config
        jsonb brand_voice
        enum status
    }
    PLUGIN_CATALOG {
        text plugin_key PK
        text interface_version
        enum[] capabilities
        jsonb content_types
        jsonb config_schema
        text auth_type
    }
    PLUGIN_CONNECTIONS {
        uuid id PK
        uuid project_id FK
        text plugin_key
        enum[] capabilities_enabled
        jsonb config
        bytea credentials_encrypted
        bytea credential_data_key_wrapped
        enum status
    }
    AGENT_CONFIGS {
        uuid id PK
        uuid project_id FK
        text agent_key
        text schedule_cron
        jsonb config
        bool enabled
    }
    AGENT_RUNS {
        uuid id PK
        uuid agent_config_id FK
        uuid project_id FK
        text agent_key
        enum status
        jsonb summary
    }
    DOMAIN_EVENTS {
        uuid id PK
        uuid project_id FK
        text event_type
        jsonb payload
        timestamptz occurred_at
        timestamptz dispatched_at
    }
    KNOWLEDGE_ITEMS {
        uuid id PK
        uuid project_id FK
        uuid source_agent_run_id FK
        text platform
        text url
        text problem
        enum buying_intent
        text[] tags
        numeric confidence
        vector embedding
    }
    CONTENT_ITEMS {
        uuid id PK
        uuid project_id FK
        text type
        enum status
        text body
        integer version
        uuid knowledge_item_id FK
        uuid created_by_agent_run_id FK
        uuid reviewed_by_user_id FK
    }
    AUDIT_LOG {
        uuid id PK
        uuid org_id FK
        uuid actor_user_id FK
        text action
        text target
        jsonb metadata
    }
    COMPANIES {
        uuid id PK
        uuid project_id FK
        text name
        text domain
        numeric icp_score
    }
    CONTACTS {
        uuid id PK
        uuid project_id FK
        uuid company_id FK
        text name
        enum status
    }
    COMPETITORS {
        uuid id PK
        uuid project_id FK
        text name
        text domain
    }
    COMPETITOR_OBSERVATIONS {
        uuid id PK
        uuid competitor_id FK
        text type
        text summary
    }
    DAILY_BRIEFS {
        uuid id PK
        uuid project_id FK
        date brief_date
        jsonb summary
    }
```

## Reading this diagram

- Every box except `ORGANIZATIONS`, `USERS`, `MEMBERSHIPS`, `PLUGIN_CATALOG`, and
  `AUDIT_LOG` (org-scoped, not project-scoped) either directly or transitively hangs off
  `PROJECTS` — this is the tenant/project scoping described in `ARCHITECTURE.md` §2 and
  `docs/database/SCHEMA.md`. `PLUGIN_CATALOG` is deliberately global (not project- or
  org-scoped at all) — it describes what plugins are *installed on this deployment*, not
  anything project-specific; `PLUGIN_CONNECTIONS` is where the project-specific data lives.
- `PLUGIN_CATALOG → PLUGIN_CONNECTIONS` is explicitly **not** a foreign key — see
  `docs/database/SCHEMA.md`'s `plugin_catalog` note for why (the catalog is rebuilt at every
  process start; a hard FK would create ordering hazards during that rebuild).
- `KNOWLEDGE_ITEMS → DOMAIN_EVENTS` and `CONTENT_ITEMS → DOMAIN_EVENTS` represent the
  transactional-outbox relationship (`ARCHITECTURE.md` §7) — an event is written in the same
  transaction as the row it describes, which this diagram can't express as a constraint but
  is the single most important property of how these tables are used together.
- `KNOWLEDGE_ITEMS → CONTENT_ITEMS` is optional (a `content_item` can exist without a
  triggering `knowledge_item`) — the FK is nullable in the DDL.
- `AGENT_RUNS` is the audit spine: both `knowledge_items` and `content_items` trace back to
  the specific run that produced them, which is what makes "why did GrowthOS suggest this"
  answerable months later.
