# Frontend

Next.js (App Router, TypeScript) dashboard — Morning Brief, Approval Inbox, Knowledge Base
Explorer, project and plugin-connection settings.

## Intended structure (Phase 1–2 implementation target)

```
frontend/
├── app/
│   ├── (dashboard)/
│   │   ├── morning-brief/          Phase 2 — the daily "what should I do" view
│   │   ├── approvals/               Phase 1 — the highest-priority view, ships first
│   │   ├── knowledge-base/          Phase 2 — search/browse knowledge_items
│   │   └── settings/
│   │       ├── projects/
│   │       ├── plugin-connections/
│   │       └── agent-configs/
│   └── layout.tsx
├── components/
│   ├── approval-inbox/               ContentItem review/approve/reject UI
│   ├── plugin-connection/
│   │   └── DynamicConnectionForm.tsx  Renders ANY plugin's connection form from its
│   │                                   config_schema (GET /api/v1/plugins/catalog) — the
│   │                                   one component that makes adding a plugin a
│   │                                   zero-frontend-code-change operation, see
│   │                                   docs/decisions/0009-plugin-config-schema-dynamic-ui.md
│   └── ui/                            Shared design-system components
├── lib/
│   ├── api-client.ts                  Typed client for backend/app/api/v1
│   └── types.ts                       Mirrors backend/app/schemas
└── package.json
```

## The Approval Inbox is the highest-stakes surface in this app

It is the only UI that can approve or reject a `content_item`
(`docs/api/API_DESIGN.md`) — every interaction design decision here should bias toward
making the human reviewer actually read what they're approving (e.g. no bulk-select-all
approve action, ever — see `docs/api/API_DESIGN.md` §"What's intentionally not in v1").

## Why Next.js over a bare SPA

Server-rendered pages suit a dashboard checked once each morning (fast initial load, good
for the Morning Brief specifically) and deploy in the same Docker Compose stack as the rest
of the system — no separate hosting platform dependency. See `README.md` (repo root) tech
stack table.

## Status

Scaffolding only — see `ROADMAP.md` Phase 1 for what ships first (Approval Inbox only, no
Morning Brief yet).
