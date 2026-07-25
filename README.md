# GrowthOS

**Architecture: Version 2 (frozen).** See [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md)
for the freeze declaration and [ARCHITECTURE.md](ARCHITECTURE.md) for the canonical design.

GrowthOS is an AI-powered operating system for solo founders. It researches the market,
finds the right people and conversations, drafts content and outreach, and tells you what to
do today to grow your SaaS business — while keeping a human in control of every public
interaction. GrowthOS never posts, messages, or publishes anything without explicit human
approval.

GrowthOS is not a marketing automation tool and it is not a spam bot. It is closer to a
research analyst and chief of staff that happens to run on a schedule.

## What it answers every morning

- Who should I talk to today?
- Which companies match my ideal customer profile?
- Which online discussions are worth joining?
- Which conversations show high buying intent?
- What content should I publish today?
- Which customers need follow-up?
- What are competitors doing?
- What product ideas keep coming up?

## How it works, in one paragraph

GrowthOS runs a set of independent **agents**, each scoped to a **project** (one of your SaaS
businesses) — some on a schedule, some triggered by **domain events** another agent's output
published (e.g. a newly discovered conversation triggers a draft, with no direct link between
the two agents' code — see `ARCHITECTURE.md` §7). Agents read external signal through
self-describing **plugins** (Reddit, LinkedIn, GSC Community, Google Analytics, etc. — and,
by design, up to 100+ over time without any core code changing) and write everything they
find into a structured **knowledge base**. When an agent wants to say something publicly — a
reply, a DM, an article — it creates a draft that sits in your **Approval Inbox** until you
approve it. Nothing goes out the door on its own. See [ARCHITECTURE.md](ARCHITECTURE.md) for
the full design.

## Repository layout

```
GrowthOS/
├── ARCHITECTURE.md        High-level system design (Version 2, frozen) — start here
├── ARCHITECTURE_FREEZE.md  The freeze declaration — what's locked before implementation
├── ROADMAP.md              What's built, what's next, what's deliberately deferred
├── CONTRIBUTING.md         How to work in this repo
├── docs/                   Design docs — one topic per subfolder
│   ├── database/           Schema + ERD
│   ├── api/                REST API design
│   ├── agents/             Agent architecture
│   ├── plugins/            Plugin architecture
│   ├── auth/                Authentication & authorization strategy
│   ├── jobs/                Background job architecture
│   ├── config/              Configuration strategy
│   ├── logging/             Logging strategy
│   ├── observability/       Metrics & tracing strategy
│   ├── errors/              Error handling strategy
│   ├── testing/             Testing strategy
│   ├── deployment/          Deployment strategy
│   ├── security/            Security considerations
│   ├── scalability/         Scalability considerations
│   ├── knowledge-base/      Knowledge base design
│   ├── reviews/             Design review reports
│   ├── architecture/        Locked decisions + archived superseded proposals
│   └── decisions/           Architecture Decision Records (ADRs)
├── agents/                  One package per agent (Customer Finder, Content Agent, ...)
├── plugins/                 One package per external integration (Reddit, LinkedIn, ...)
├── backend/                 FastAPI application (API, services, domain models, migrations)
├── frontend/                Next.js dashboard (Morning Brief, Approval Inbox, ...)
├── database/                Schema DDL and migration source of truth
├── docker/                  Dockerfiles and compose configuration
├── scripts/                 Dev/ops scripts (setup, seed, migrate, lint)
└── tests/                   Cross-cutting integration and end-to-end tests
```

Each agent and plugin package has its own `README.md`, config, prompts, tools, and tests —
see `agents/<name>/README.md` and `plugins/<name>/README.md`.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Async-native, typed, matches the LLM-call-heavy I/O workload |
| Database | PostgreSQL + pgvector | Relational core + embeddings in one system, one backup story |
| Cache / queue broker | Redis | Also backs Arq, event dispatch, and rate limiting |
| Background jobs & event dispatch | Arq | Async-native, Redis-backed, far less operational overhead than Celery — and, since V2, also the fan-out mechanism for the domain-event architecture instead of a dedicated broker |
| Event log | PostgreSQL (`domain_events`, transactional outbox) | Agents communicate by publishing/subscribing to events, not by calling each other — see `ARCHITECTURE.md` §7 |
| LLM providers | Anthropic Claude (primary), OpenAI (secondary) | Claude for reasoning/drafting/judgment; OpenAI for embeddings and bulk/cheap classification; both behind one provider interface |
| Frontend | Next.js (TypeScript, App Router) | Server-rendered dashboard, ships in the same Docker Compose stack; one generic schema-driven form renders every plugin's connection UI |
| Infra | Docker Compose (v1), documented path to Kubernetes | Right-sized for a single-operator deployment today |
| Config | `.env` via `pydantic-settings` | Typed, validated at startup, one file per environment |
| Observability | OpenTelemetry + Prometheus/Grafana | Per-plugin and per-agent metrics — necessary at a 100+ plugin surface where logs alone don't answer "what's degraded right now" |

Full reasoning for each choice: `docs/decisions/`.

## Status

Phase 0 is complete: design documentation, a Principal Engineer design review, and the
resulting Version 2 architecture, frozen — see [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md).
This repository still contains **design documentation and project scaffolding only** — no
production code has been written yet, by design. See `ROADMAP.md` Phase 1 for what's built
first and in what order.

## Getting started (once implementation begins)

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

See `docs/deployment/DEPLOYMENT.md` for environment-by-environment detail and
`scripts/README.md` for local dev scripts.
