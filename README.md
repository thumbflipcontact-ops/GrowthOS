# GrowthOS

**Architecture: Version 2 (frozen).** See [ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md)
for the freeze declaration and [ARCHITECTURE.md](ARCHITECTURE.md) for the canonical design.
**Platform foundation: implemented and tested (Phase 1).** See
[PHASE_1_REPORT.md](PHASE_1_REPORT.md).

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

Phase 0 (architecture) and Phase 1 (platform foundation) are both complete — see
[ARCHITECTURE_FREEZE.md](ARCHITECTURE_FREEZE.md) for the frozen design and
[PHASE_1_REPORT.md](PHASE_1_REPORT.md) for what was built, tested, and verified. The backend
has a real FastAPI app, database schema + migrations, auth, the plugin SDK/registry, a
generic OAuth2 framework, the event bus, and background job plumbing — all with a passing
test suite. Three channel plugins are now implemented, all against the generic OAuth2
framework: Reddit (searchable + publishable) — see
[docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md](docs/reviews/REDDIT_PLUGIN_IMPLEMENTATION_REPORT.md)
— and Twitter/X (searchable + publishable, OAuth2 + PKCE) and LinkedIn (publishable only —
LinkedIn's public API has no general content-search endpoint) — see
[docs/reviews/TWITTER_LINKEDIN_IMPLEMENTATION_REPORT.md](docs/reviews/TWITTER_LINKEDIN_IMPLEMENTATION_REPORT.md).
See `ROADMAP.md` for what's next.

## Getting started

No Docker required for local development — see [PHASE_1_REPORT.md](PHASE_1_REPORT.md) for
why and `docker/README.md` for the (currently unverified) Docker-based alternative.

```bash
python scripts/setup.py                       # creates backend/.venv, installs deps, .env
# in one terminal — a real, embedded local Postgres, no install/Docker needed:
cd backend && .venv/Scripts/python scripts/dev_postgres.py   # Windows
cd backend && .venv/bin/python scripts/dev_postgres.py       # macOS/Linux
# in another terminal:
python scripts/migrate.py                     # apply the database schema
python scripts/seed.py                        # optional: demo org/user
cd backend && .venv/Scripts/python -m pytest -p no:cov   # run the test suite (Windows)
cd backend && .venv/bin/python -m pytest -p no:cov        # (macOS/Linux)
```

See `scripts/README.md` for what each script does and `docs/deployment/DEPLOYMENT.md` for
environment-by-environment detail.

## License

AGPL-3.0 — see [LICENSE](LICENSE). Chosen over a permissive license specifically because
GrowthOS is offered as a hosted service: AGPL's network-use clause means anyone who runs a
modified version of GrowthOS as a service for others must also make that modified source
available, closing the "fork it, host it, undercut the original" loophole that a permissive
license leaves open.
