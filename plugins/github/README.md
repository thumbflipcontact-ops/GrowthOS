# Plugin: GitHub

**Capabilities:** `Searchable`, `Publishable`

## Purpose

Searches issues/discussions across configured repos (competitor open-source projects,
relevant tooling repos) for problems worth engaging with, and can find companies/contacts
via public commit/profile data for `customer_finder`. Also comments on issues/discussions
when approved.

## Auth

GitHub App or PAT with `repo` (read) and `issues:write`/`discussions:write` scopes,
depending on target repos' visibility. Stored encrypted.

## `search()`

Wraps the GitHub Search API (issues, discussions, code where relevant) scoped to configured
repos or search qualifiers from project config.

## `publish()`

Comments on an issue/discussion referenced by `ContentItem.target_ref`.

## Rate limits

GitHub's REST API: 5,000 requests/hour per authenticated app — generous relative to the
other plugins; the shared rate limiter still applies for consistency and to protect against
runaway queries.
