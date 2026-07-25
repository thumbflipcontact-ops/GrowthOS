# ADR 0001: Tenant-ready schema, solo-first product

**Status:** Accepted — 2026-07-24

## Context

GrowthOS runs ScoutSEO today and is explicitly intended to run additional SaaS businesses the
founder owns. A separate, larger question is whether GrowthOS itself will ever be sold as a
product to other founders (true multi-tenant SaaS). At founding time, the answer is: not
now, possibly later, undecided.

Three options were considered:
1. Build strictly for single-operator use — no org/tenant abstraction at all.
2. Build full multi-tenant SaaS now — signup, billing, role-based access, tenant isolation
   enforcement.
3. Design the schema and auth model as tenant-ready (org/project scoping on every table) but
   ship v1 with exactly one organization and no signup/billing flow.

## Decision

Option 3. Every domain table carries `project_id` (which transitively scopes to
`organization_id` via `projects.org_id`, see `docs/database/SCHEMA.md`), and the
`membership_role` enum already includes both `owner` and `member`, even though v1 only ever
creates `owner` memberships. No signup flow, billing, or multi-user invitation UI is built in
v1.

## Consequences

**Positive:** if GrowthOS is later sold as a product, activating multi-tenancy (Phase 4, see
`ROADMAP.md`) is building new flows (signup, invitations, billing) on top of an already-
correct data model — not a schema migration and backfill across every table while the system
is in active daily use. This asymmetry (cheap now, expensive later) is the entire justification
for paying the cost today.

**Cost accepted:** every table has one more join-relevant column and every service-layer
query must be written with explicit project scoping from day one, even though v1 has exactly
one project's worth of data to scope against. This is a small, constant tax, paid once per
table at design time, not a recurring cost.

**What this decision does NOT include:** Row-Level Security policies, actual signup/billing
code, or fine-grained permissions beyond `owner`/`member`. Those remain Phase 4 scope — see
`docs/security/SECURITY.md` and `ROADMAP.md`.
