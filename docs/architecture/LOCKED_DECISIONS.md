# Decisions Locked Before Implementation

This is the actual "architecture freeze" — the set of decisions that implementation should
treat as settled. Each links to the ADR or document with the full reasoning. A locked
decision isn't permanent forever (see `docs/decisions/README.md`'s supersession convention),
but it should not be relitigated mid-implementation without a new ADR and a deliberate reason.

Separately, §2 lists decisions that are **deliberately left flexible** — settling these now
would be exactly the kind of premature specificity this review pushed back on elsewhere.

This document reflects the *frozen* state: the V2 proposal and the V1→V2 migration plan that
produced it have both been executed and archived under
[`docs/architecture/archive/`](archive/) for historical record. `ARCHITECTURE.md` at the repo
root is the only current architecture document — see
[`ARCHITECTURE_FREEZE.md`](../../ARCHITECTURE_FREEZE.md) for the freeze declaration.

## 1. Locked

| # | Decision | Reference |
|---|---|---|
| L1 | Tenant-ready schema (`project_id`/`org_id` scoping everywhere), solo-first product, no billing/signup in v1 | ADR 0001 |
| L2 | Arq (not Celery) for background jobs — and now also the event-dispatch mechanism | ADR 0002 |
| L3 | Agents never call each other directly or import each other; all cross-agent communication is through the data layer | ADR 0003 (conclusion retained), ADR 0006 (mechanism revised) |
| L4 | Agent-to-agent coordination is event-subscription based (`domain_events` transactional outbox + Arq dispatch), not orchestrator sequencing config and not a dedicated message broker | ADR 0006, `ARCHITECTURE.md` §7 |
| L5 | Claude is the primary LLM provider; OpenAI is secondary, behind one `LLMProvider` interface | ADR 0004 |
| L6 | Reddit is the first plugin implemented | ADR 0005 |
| L7 | Plugins are discovered via self-describing manifests + entry points; the core plugin registry is a scanner, never a hand-maintained list | ADR 0007, `ARCHITECTURE.md` §5 |
| L8 | Plugin capabilities are segmented Protocols (`Searchable`, `Publishable`, `WebhookReceivable`, `MetricsQueryable`), not one fat interface gated by a runtime enum | ADR 0007, `ARCHITECTURE.md` §5 |
| L9 | `content_items.type` is validated at the application layer against installed plugins' declared content types — never a closed database enum | ADR 0008, `ARCHITECTURE.md` §6 |
| L10 | Every plugin declares a config JSON Schema; the frontend renders connection forms generically from it — no plugin-specific frontend code | ADR 0009, `ARCHITECTURE.md` §6 |
| L11 | Plugin credentials are protected by envelope encryption (rotatable master key wrapping per-connection data keys), not a single static key | ADR 0010, `ARCHITECTURE.md` §9 |
| L12 | The `ContentItem` approval transition (`pending_review → approved/rejected`) must be guarded against concurrent double-transition (row lock or version column) | `docs/reviews/DESIGN_REVIEW.md` §3.2 |
| L13 | REST over GraphQL/gRPC for the API | `docs/api/API_DESIGN.md` (unchanged, reaffirmed) |
| L14 | Docker Compose over Kubernetes for the current deployment target | `docs/deployment/DEPLOYMENT.md` (unchanged, reaffirmed) |
| L15 | No autonomous publishing, ever, for any plugin, at any phase — the approval gate is permanent, not a v1 limitation | `ARCHITECTURE.md` §8, `ROADMAP.md` §Non-goals |

**L1–L6 and L13–L15 carry forward from the original design unchanged** — this review checked
them adversarially and found no fault; they're listed here for completeness, not because
anything about them is new.

**L7–L12 are the actual output of this review** — none of these existed as explicit decisions
before this pass; they were either implicit-and-wrong (L7, L9), missing (L4, L10, L12), or
underspecified (L8, L11).

## 2. Explicitly left flexible

Locking these now would be false precision — they're implementation details with low
switching cost, and deciding them today would mean guessing ahead of information
implementation will actually produce.

| Decision | Why it's flexible | Revisit when |
|---|---|---|
| Metrics backend: self-hosted Prometheus/Grafana vs. a hosted alternative | Same OpenTelemetry instrumentation either way — this is a deployment choice, not an architecture choice | `docs/observability/OBSERVABILITY.md` implementation |
| Frontend schema-form rendering library | Any JSON-Schema-driven form library satisfies L10; pick based on actual Next.js ecosystem fit when building it | When implementing `DynamicConnectionForm` |
| Envelope-encryption master key storage: local secret vs. cloud KMS | L11 only requires the envelope *pattern*; where the master key lives is swappable without touching the encryption scheme | Before first production plugin credential is stored — see `docs/security/SECURITY.md` |
| Event dispatcher poll interval | Tune based on observed webhook-to-reaction latency needs once real webhook plugins exist | Phase 2, when `email`/`slack`/`discord` plugins are built |
| Plugin sandboxing / isolation | Explicitly deferred, not decided — current trust model assumes first-party, reviewed plugin code only | Before accepting any plugin not personally written/reviewed by you — see DESIGN_REVIEW §5.4 |
| Login brute-force protection mechanism (rate limit vs. lockout vs. CAPTCHA) | The requirement (*some* protection must exist) is locked in spirit; the mechanism isn't | Phase 1 auth implementation, low effort either way |
| Audit log schema detail | Needs to exist (DESIGN_REVIEW §5.3); exact columns can follow whatever `content_items`' review-trail pattern suggests once built | Alongside the Approval Inbox / publish worker implementation |
| Postgres Row-Level Security timing | Still Phase 4 by default (ADR 0001); could move earlier as defense-in-depth if it turns out cheap once the schema is stable | Reassess after Phase 1 schema is implemented and stable |

## 3. What "locked" obligates

An implementer hitting an L1–L15 decision mid-Phase-1 should build to it, not relitigate it
inline. A genuine objection discovered during implementation (something in this review turns
out to be wrong once real code exists) gets a new ADR marked `Supersedes 000X`, not a silent
deviation — see `docs/decisions/README.md`.
