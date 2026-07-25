# ADR 0005: Reddit as the first plugin implemented

**Status:** Accepted — 2026-07-25

## Context

`ROADMAP.md` Phase 1 needs exactly one plugin to prove the full loop — discovery →
knowledge item → drafted reply → human approval → real publish. `docs/plugins/PLUGIN_ARCHITECTURE.md`
had shortlisted Reddit and GSC Community as the two strongest candidates for ScoutSEO's ICP,
deferring the choice to implementation time. That choice is now made.

## Decision

**Reddit** is the first plugin implemented, ahead of GSC Community and everything else.

Reasoning:
- **Official, documented, well-supported API.** Reddit's API (and mature client libraries
  like PRAW) is a known quantity with predictable auth (OAuth2), rate limits, and response
  shapes. GSC Community runs on Google Groups infrastructure with no first-class public API
  — its own `README.md` flags that it likely needs a scraping-based approach, which is a
  strictly harder and less certain integration to get right first.
- **Both capabilities in one place.** Reddit supports `Searchable` and `Publishable` through
  the same well-documented API, which is exactly what Phase 1 needs to exercise the full loop
  (discovery *and* the approval-gated publish path) without needing a second plugin to prove
  the publish side works at all.
- **Faster path to the Phase 1 exit criterion.** The goal of Phase 1 is proving the trust
  model end-to-end as fast as credibly possible (`ARCHITECTURE.md` §7). A plugin with more
  integration risk (undocumented API, scraping fragility) working correctly is a weaker
  first proof point than a plugin whose only real risk is "did we implement the OAuth flow
  and rate limiting correctly."
- **Real relevance to ScoutSEO's ICP.** Reddit communities like r/SEO, r/juststart, and
  similar are genuinely where SaaS founders debugging Search Console issues show up — this
  isn't a toy choice made purely for engineering convenience.

## Consequences

**Positive:** Phase 1 has one clear, well-scoped integration target instead of two
candidates to evaluate mid-implementation. `plugins/reddit/README.md` is the concrete spec
to build against first.

**Deferred, not rejected:** GSC Community remains a strong Phase 2 candidate — its higher
integration risk (no public API) is exactly the kind of thing better tackled once the rest
of the system (approval flow, orchestrator, agent framework) is already proven against a
simpler integration, rather than debugging both at once. See `ROADMAP.md` Phase 2.
