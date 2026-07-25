# Plugin: CRM

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Generic adapter for syncing `contacts`/`companies` to an external CRM (e.g. HubSpot,
Pipedrive) for founders who already run one and don't want GrowthOS's CRM-lite tables to be
the system of record. Phase 3, alongside `crm_assistant`.

## Auth

Provider-specific OAuth2/API key, stored encrypted. This plugin is intentionally generic in
its `README`/interface — the concrete provider (HubSpot vs. Pipedrive vs. other) is a
project-level config choice, not a code fork; if two different CRM providers are ever needed
simultaneously, that's two plugins (`crm_hubspot`, `crm_pipedrive`) sharing a common base
module under `plugins/_shared/`, not branching logic inside one plugin.

## `search()` / `publish()`

`search()` reads existing CRM records to avoid duplicate creation; `publish()` pushes
GrowthOS-sourced `contacts`/`companies` updates (new contact discovered, status change) to
the external CRM.

## Status

Not yet scoped to a specific provider — deferred to Phase 3 per `ROADMAP.md`.
