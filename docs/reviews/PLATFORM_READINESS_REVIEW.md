# Platform Readiness Review — Building Plugin #10

**Date:** 2026-07-25
**Reviewer stance:** an external developer who has never seen GrowthOS before, asked to
build the 10th plugin — not the first. Nothing here is about `ARCHITECTURE.md`'s design
decisions (those are frozen and out of scope) or code quality/style. This is about the
platform surface a plugin author actually touches: the SDK, the docs, the tooling, the
lifecycle — evaluated by trying to actually use it, not by re-reading the design docs and
trusting them.

**Method:** every finding below was verified against the real repository state as of this
commit — file existence checked, code read, cross-references followed — not inferred from
what the design docs *say* should exist. Several findings are exactly this: a doc promising
something that isn't there.

**Headline verdict:** the core mechanism (manifest, segmented capability Protocols, registry,
two-gate enforcement) is genuinely solid and is the part of this platform closest to
production quality — see `PHASE_1_REPORT.md` §2 for how thoroughly it's tested. **The
developer-facing surface around that mechanism is not ready for a 10th external contributor.**
A person building plugin #2 would already be improvising past several points where the docs
point at infrastructure that doesn't exist. See §5 for the full "is this production-quality"
answer.

---

## 1. Platform Readiness Report

### What's ready

- The manifest → entry-point discovery → catalog → registry → two-gate capability check
  pipeline works, is tested end-to-end against a real installed package
  (`plugins/dummy/`), and its error messages are specific and actionable (`plugin_key` and
  capability name are always present — see `plugin_registry.py`'s `CapabilityNotSupported`
  raises).
- The segmented-Protocol design (`Searchable`/`Publishable`/`WebhookReceivable`/
  `MetricsQueryable`) is a genuinely good extension point: a plugin author only implements
  what they need, and `mypy`/`isinstance` both enforce it structurally.
- `plugin_key` naming and capability-string naming are consistent and predictable
  (`Searchable` ↔ `"searchable"`, etc.) once you've seen one example.

### What's not ready

- **Two pieces of documented, load-bearing infrastructure don't exist**:
  `plugins/_shared/tests/test_plugin_contract.py` (told to plugin authors twice — in
  `CONTRIBUTING.md` and `docs/plugins/PLUGIN_ARCHITECTURE.md` — as the thing you run against
  your plugin) and `plugins/_shared/rate_limit.py` (told to plugin authors as "the shared
  helper" for respecting external rate limits). Both are `grep`-verified absent.
- **A plugin cannot actually be connected to a project.** `GET /api/v1/plugins/catalog`
  exists; the `POST .../plugin-connections` endpoint `docs/api/API_DESIGN.md` documents does
  not — there is no code path from "I built a plugin" to "a project is using it" today.
- **OAuth2 plugins — Reddit, the designated first plugin — have no documented mechanism.**
  `docs/auth/AUTHENTICATION.md` says exactly one sentence: "Plugin OAuth flows ... use the
  standard OAuth2 authorization-code flow." No redirect URI convention, no callback endpoint,
  no state-param handling, no indication of who initiates the flow or where the manifest
  would declare `authorize_url`/`token_url`/`client_id`. This is the single largest gap for
  the very next thing this project does.
- **A structural gap in the event-publishing contract for `WebhookReceivable` plugins** —
  see §3, this is the most important individual finding in this review.
- **No scaffolding.** Every new plugin hand-writes a `pyproject.toml` using an obscure
  setuptools trick (`package-dir = {"plugins.dummy" = "."}`) that most Python developers have
  never needed. There is no `plugins/dummy/tests/` to copy from — the one example plugin has
  no tests at all, contradicting the one thing the "how to add a plugin" checklist emphasizes
  most.

### Bottom line

If you handed this repository to a competent Python developer today and asked them to build
Reddit as plugin #1, they would get through the manifest and the four Protocols without
trouble, then hit a wall at "how do I actually get a plugin installed and discoverable
locally" (undocumented), "how do I test it" (promised infra missing), "how do I do OAuth"
(one sentence, no mechanism), and "how do I connect it to a project" (endpoint doesn't
exist). None of these are hard problems — they're all solvable in an afternoon each — but
none of them are solved yet, and the docs currently read as if they are.

---

## 2. Developer Experience Review

Walking through what `docs/plugins/PLUGIN_ARCHITECTURE.md` §"How to add a new plugin" and
`CONTRIBUTING.md` §"Adding a new plugin" actually tell you to do, in order:

**Step 1: "Create `plugins/<name>/` — `manifest.py`, `client.py`, `plugin.py` ..., `README.md`,
`tests/`."** `client.py` is listed as required in both documents. Nothing anywhere explains
what belongs in `client.py` versus `plugin.py`, and the one working example
(`plugins/dummy/`) doesn't have one — its `plugin.py` does everything. A developer has no way
to know whether `client.py` is "the HTTP client wrapper, kept separate for testability" (a
reasonable guess) or something more specific, because it's never modeled.

**Step 2: declare the manifest.** This part is genuinely smooth — the dataclass is small,
the example in the docs matches reality, and `config_json_schema()` doing the pydantic → JSON
Schema conversion for you is a nice touch.

**Step 3: implement the Protocols.** Also smooth, with one friction point: `Publishable.publish`
is typed `async def publish(self, item: object) -> PublishResult`. `object` gives a plugin
author zero IDE assistance for what fields a `ContentItem` actually has (`.body`, `.type`,
`.target_ref`, ...) — they have to go read `ARCHITECTURE.md` §8 and
`database/schema.sql` to find out, because the SDK's own type signature won't tell them.
This is a deliberate trade-off (`plugins/_shared` can't import `backend/app`'s ORM model) but
it's an ergonomics cost nobody has mitigated — a `Protocol`-shaped `ContentItemView` with
just the fields a plugin needs would cost little and remove this entirely.

**Step 4: "Register the entry point in `pyproject.toml`."** Correct, but the *specific*
setuptools incantation needed for a package that lives inside a monorepo subdirectory but is
installed as its own distribution (`packages = [...]`, `package-dir = {...}`) is nowhere
explained — a developer has to reverse-engineer it from `plugins/dummy/pyproject.toml`, which
itself has zero comments explaining why it's shaped that way. **Nothing tells you that you
then have to `pip install -e` that directory into the backend's virtualenv for the entry
point to actually register** — this was tribal knowledge from implementing Phase 1, never
written down anywhere a plugin author would find it.

**Step 5: "Write tests, including the shared contract test suite ... parameterized against
your plugin."** The file this refers to doesn't exist. A developer following the checklist
literally will search the repo for it, not find it, and have no idea whether that's their
mistake or the documentation's.

**What happens when something goes wrong?** If a plugin's `manifest.py` has a bug that makes
it fail to import, `discover_installed_plugins()` logs an error and silently excludes it from
the catalog — `except Exception: ... continue`. A plugin author who made a typo gets no
exception, no test failure, nothing but a structured log line they'd need to already know to
go look for. "Why doesn't my plugin show up in the catalog?" is going to be a common support
question with the current design, not a rare one.

**Net assessment:** the first 30 minutes (manifest, Protocols) feel good. The next several
hours (packaging, local install, testing, connecting to a project, OAuth) are entirely
unguided, and at least three of those five have infrastructure the docs promise but that
isn't there.

---

## 3. Plugin SDK Review

### The good

- `plugins/_shared/base.py` and `manifest.py` are genuinely dependency-free of `backend/app`,
  as documented — verified, not just claimed. This matters for the "100+ plugins,
  open-source development" goal: a plugin author's `pip install` doesn't drag in FastAPI,
  SQLAlchemy, or anything backend-specific.
- The four capability Protocols are the right shape — narrow, composable, and
  `@runtime_checkable`, so `isinstance` checks actually work at the registry boundary. This
  is not a common thing to get right in a Python plugin system and it's done correctly here.
- `ContentTypeSpec` and the plugin-contributed-content-type design (ADR 0008) genuinely
  delivers on "a plugin introducing a new content shape needs zero core schema changes" — I
  traced this through the actual `content_items.type` column (confirmed `text`, not an enum)
  and it holds up.

### A real structural gap: `WebhookReceivable` plugins cannot do what they're documented to do

`docs/plugins/PLUGIN_ARCHITECTURE.md` §"Webhooks and events" states:

> A `WebhookReceivable` plugin's `handle_webhook()` writes its resulting row ... and that
> row's domain event (`knowledge_item.created`) in a single transaction

But `EventPublisher` and `DomainEvent` both live in `backend/app/core/events.py` and
`backend/app/models/event.py` — inside the package `plugins/_shared` is explicitly designed
to never depend on (correctly, for the reasons stated in `base.py`'s own docstring). Nothing
in `plugins/_shared` exposes a way for a plugin's `handle_webhook()` implementation to
publish a domain event at all. As written, a `WebhookReceivable` plugin has no legal way to
fulfil what its own architecture doc says it must do. This isn't a documentation typo — it's
a real interface the platform needs and doesn't have: something like an injected
`EventPublisher`-shaped Protocol passed into `handle_webhook()` (or into the plugin
constructor alongside `connection`), typed narrowly enough that `plugins/_shared` doesn't
need to import `backend/app` to reference it. Three of the twelve plugins on the roadmap
roster (`email`, `slack`, `discord`) declare `webhook_receivable` — this blocks all three,
not a hypothetical edge case.

### Smaller SDK ergonomics issues

- **No re-export surface.** `plugins/_shared/__init__.py` is empty. A plugin author writes
  `from plugins._shared.base import Searchable, PluginQuery` and
  `from plugins._shared.manifest import PluginManifest, ContentTypeSpec` as two separate
  imports from two separate modules, for no reason a plugin author would understand — nothing
  stops `plugins/_shared/__init__.py` from re-exporting the common surface as one import.
- **`PluginQuery`/`PluginResult` are unvalidated dataclasses next to a `pydantic`-validated
  `config_schema`.** Two different validation philosophies in the same SDK, with no
  explanation of why (the reasonable reason — SDK dependency-weight discipline, pydantic only
  where it earns its cost — is never stated, so it reads as inconsistency rather than a
  choice).
- **`MetricsResult.rows: list[dict]`** — comment says "shape declared by the plugin's own
  documentation," which is a reasonable call for genuinely heterogeneous data, but means
  `MetricsQueryable` is the one capability with zero structural guarantee at all. Combined
  with zero real example of a `MetricsQueryable` plugin existing yet, a future author has
  nothing to model against.
- **Two registry methods disagree on failure handling.** `PluginRegistry.get()` lets a
  plugin-construction exception propagate; `all_with_capability()` swallows any exception
  from the same code path (`except Exception: continue`). At 100+ plugins, one misbehaving
  plugin will crash an agent calling `.get()` for it by name while being silently invisible
  to an agent calling `all_with_capability()` — same failure, two different observable
  behaviors depending on which method call reached it. Worth deciding once, not twice.

---

## 4. Recommended improvements before Plugin #1

In the order they'd actually block someone:

1. **Design and document the OAuth2 connection flow.** Redirect/callback endpoint(s), where
   `authorize_url`/`token_url`/`client_id`/`scope` live (manifest? a separate OAuth config
   block?), state-param CSRF handling, and how the resulting token reaches
   `credentials_encrypted`. Reddit cannot be built without this.
2. **Close the `WebhookReceivable` event-publishing gap** (§3) — decide the shape of what
   gets passed into `handle_webhook()` so a plugin can legally publish a domain event.
3. **Build `POST /api/v1/projects/{project_id}/plugin-connections`**, including the config
   validation against `manifest.config_json_schema()` that's documented as happening but
   isn't implemented anywhere yet (`grep`-verified — nothing calls a JSON-Schema validator
   against a connection's `config`).
4. **Either build `plugins/_shared/tests/test_plugin_contract.py` or stop telling plugin
   authors it exists.** If it's genuinely Phase 2 work, say so in the docs instead of
   presenting it as available today.
5. **Either build `plugins/_shared/rate_limit.py` or stop telling plugin authors it's
   there.** Same issue, same fix.
6. **Give `plugins/dummy/` a `tests/` directory.** It's the only worked example in the
   repository; right now it demonstrates skipping the one step the checklist calls most
   important.
7. **Write a real quickstart** — a single "clone, create a plugin package, install it, see it
   in the catalog, write one test, done" walkthrough distinct from
   `PLUGIN_ARCHITECTURE.md` (which is a design-rationale document, not a tutorial — both are
   needed, only one exists). Include the `pip install -e` step explicitly; it's currently
   undocumented anywhere.
8. **Add a scaffolding script** (`scripts/new_plugin.py <name>` in the same spirit as
   `scripts/setup.py`) that generates the `pyproject.toml` boilerplate, the entry point, and
   a skeleton `manifest.py`/`plugin.py`/`tests/` — removing the setuptools trick as something
   a human ever has to get right by hand.
9. **Fix the two stale path references** in code comments: `plugin_registry.py`'s docstring
   points at `backend/tests/fixtures/dummy_plugin`, which doesn't exist — the real fixture is
   `plugins/dummy/`.
10. **Decide and document `interface_version` semantics** — is `"1.0"` → `"1.1"` compatible
    or not? Right now `SUPPORTED_INTERFACE_VERSIONS` is an exact-string allowlist with no
    semver comparison, which is fine at 1 plugin and will be a real maintenance tax at 100 if
    every non-breaking SDK addition requires every plugin to bump and re-declare.

---

## 5. Is this production-quality for plugin development?

**Not yet, and I want to be precise about which half of that sentence is true.**

The **mechanism** — manifest discovery, segmented capability Protocols, the registry's
two-gate enforcement, plugin-contributed content types — is production-quality. It's
well-designed, it's tested against a real installed package rather than a mock, and nothing
in this review found a reason to distrust it.

The **developer experience wrapped around that mechanism** is not production-quality yet,
specifically because the documentation describes a more finished platform than exists: a
test harness that isn't built, a rate-limit helper that isn't built, a config-validation path
that isn't built, a connection API that isn't built, and an OAuth mechanism that's one
sentence long. None of these are individually hard — most are a day or two of focused work
each — but collectively they're exactly the set of things a developer building plugin #2
through #10 would need and not have, and every one of them would currently be discovered by
hitting a wall, not by reading a doc that says "not yet."

**Recommendation:** treat §4 as a short, sequenced pre-Plugin-1 punch list (it doubles as the
Reddit-plugin blocker list, since Reddit needs OAuth + the connection API regardless), not a
reason to redesign anything. The frozen architecture doesn't need to change for any of this —
it needs the parts of itself it already promised to be built.

---

## 6. Priority-ranked checklist

| # | Item | Blocks Reddit? | Effort | Why it's ranked here |
|---|---|---|---|---|
| 1 | Design + document plugin OAuth2 flow | **Yes** | Medium | Reddit is OAuth2; nothing else can start without this |
| 2 | Close `WebhookReceivable` event-publishing gap | Not for Reddit, but blocks 3 roadmap plugins | Small | Structural gap, not a style issue — currently impossible to implement correctly |
| 3 | Build `POST .../plugin-connections` + config validation | **Yes** | Medium | No way to actually use a finished plugin without this |
| 4 | Reconcile docs vs. reality: `test_plugin_contract.py`, `rate_limit.py` | No | Small | Either build them or stop promising them — actively misleading otherwise |
| 5 | Add `tests/` to `plugins/dummy/` | No | Small | The only example currently models skipping tests |
| 6 | Write a plugin quickstart tutorial | No | Small | Cuts onboarding time for every plugin after this one |
| 7 | Add a plugin scaffolding script | No | Medium | Removes the setuptools trick as tribal knowledge |
| 8 | Fix stale `backend/tests/fixtures/dummy_plugin` references | No | Trivial | Actively points a developer at the wrong location |
| 9 | Decide `interface_version` semantics (semver vs. allowlist) | No | Small | Cheap now, a real tax at plugin #50+ if deferred |
| 10 | Reconcile `get()` vs. `all_with_capability()` failure handling | No | Small | Inconsistent blast radius for the same failure mode |
| 11 | `client.py` vs `plugin.py` — document or drop the split | No | Trivial | Currently required by docs, unused by the only example |
| 12 | Re-export common SDK surface from `plugins/_shared/__init__.py` | No | Trivial | Small but free ergonomics win |

Items 1–3 are the genuine pre-Plugin-1 blockers. Items 4–12 are pre-Plugin-10 items — Reddit
can technically be built while they're still open, but every plugin after it pays the same
tax again until they're closed.
