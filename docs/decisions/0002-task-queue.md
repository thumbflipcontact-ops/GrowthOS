# ADR 0002: Arq over Celery for background jobs

**Status:** Accepted — 2026-07-24

## Context

GrowthOS's original stack preferences listed "background workers" without specifying a
library; Celery is the default assumption for Python background jobs. GrowthOS's actual
workload is agent runs and publish jobs — overwhelmingly I/O-bound (LLM API calls, external
plugin API calls), not CPU-bound, and the application is already built on async FastAPI.

## Decision

Use **Arq** instead of Celery.

Reasoning:
- Arq is async-native (built on `asyncio` and `redis.asyncio`), matching FastAPI's execution
  model directly — no thread-pool bridging between sync Celery workers and the async plugin/
  LLM client code every agent and plugin uses.
- Arq's operational surface is a fraction of Celery's: Redis alone as both broker and result
  store (no separate result backend decision), no Flower dependency for basic job
  visibility, dramatically simpler worker configuration.
- Celery's strengths — complex workflow DAGs (chains, chords, canvas), an enormous plugin
  ecosystem, support for many broker/backend combinations — aren't needed here. GrowthOS's
  job execution model (`docs/jobs/BACKGROUND_JOBS.md`) is deliberately simple — schedule-
  triggered or domain-event-subscription-triggered (`ARCHITECTURE.md` §7, ADR 0006), not
  arbitrary workflow DAGs — by design, not as a limitation this decision imposes. Arq later
  also became the event-dispatch mechanism itself (ADR 0006), reinforcing rather than
  straining this choice.

## Consequences

**Positive:** simpler worker deployment (`docs/deployment/DEPLOYMENT.md`), less code needed
to bridge async application code into job execution, one less piece of infrastructure
(no dedicated result backend or Flower service) to operate.

**Accepted trade-off:** Arq's ecosystem and community size is much smaller than Celery's —
less Stack Overflow coverage, fewer third-party integrations, and if GrowthOS's job
orchestration needs ever grow genuinely complex (real multi-step DAGs with conditional
branching, not just sequential phases), Celery or a dedicated workflow engine (e.g. Temporal)
would need reconsideration. This is judged unlikely at GrowthOS's actual scale (single
operator, phase-sequenced agent runs) but is the concrete condition that would revisit this
decision.
