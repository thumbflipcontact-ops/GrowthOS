# Internal Beta Readiness Report

**Date:** 2026-07-26
**Scope:** everything required to install, configure, run, and debug GrowthOS end to end
against real accounts — no new business features, per this task's explicit instruction. This
phase turned the platform (feature-complete and hardened as of Phase 2D) into something an
operator can actually get running, not just something that passes a test suite.

**Method:** every claim below was verified by actually doing it — a real (embedded) Postgres
was started, real migrations were run, the new onboarding/status/environment-check tooling
was executed against that real database, and every failure encountered along the way was
fixed, not just noted. Two genuine, previously-unknown bugs were found this way (§2) — the
kind of thing that would have blocked a real operator's very first attempt to follow this
project's own documented setup steps.

---

## 1. What was built

**Operational scripts** (`scripts/`):
- `check_env.py` — validates `.env`, tests real Postgres/Redis connectivity, checks the
  database is at the expected migration revision, confirms the plugin catalog loads, flags
  placeholder secrets and API keys. The single most valuable new tool here — a first-run
  operator's first command, and a troubleshooting operator's first command.
- `status.py` — read-only operational dashboard: plugin connections, agent configs, recent
  runs, content-item counts by status, publish failures needing attention, event-dispatch
  backlog.
- `onboard.py` — interactive wizard creating a real org/user/project, printing tailored
  next-step commands with real IDs filled in.
- `_bootstrap.py` — shared fix for a real bug (§2) affecting every script that imports
  `backend/app` code directly.

**Example configurations** (`docs/examples/`): ready-to-use, schema-validated request bodies
for connecting Reddit and configuring both agents — each value checked directly against the
real pydantic model it validates against, not just written to look plausible.

**Documentation** (`docs/beta/`): Setup Guide, Deployment Guide, Troubleshooting Guide, First
Run Checklist, Known Limitations, and a phased Beta Test Plan — see §5 for how these fit
together.

**No business logic changed.** Nothing in `agents/`, `plugins/`, or any API route's behavior
was touched — this phase is entirely installation, configuration, diagnostics, and docs, per
the explicit scope given.

---

## 2. Real bugs found and fixed while building this

Building tooling that actually *runs* the setup process (rather than just describing it)
surfaced two genuine, reproducible bugs that had been sitting in this project's own documented
Quickstart the whole time — the kind of thing only surfaces when someone actually executes the
happy path from a clean state, which nothing had done until this phase.

**`scripts/migrate.py` never actually loaded `.env`.** The script's own docstring claimed
`DATABASE_URL` is read "from the environment or backend/../.env," but it only shells out to
`alembic`, whose `env.py` reads `os.environ` directly — it never loads `.env` itself (only the
app's pydantic-settings `Settings` object does that, and this script never constructs one).
Reproduced directly: `python scripts/migrate.py` against a fresh `.env` failed with a
confusing `Can't load plugin: sqlalchemy.dialects:driver` error — alembic silently fell back
to `alembic.ini`'s placeholder URL. Fixed by having `migrate.py` load `.env` itself (a
minimal, dependency-free parser — `python-dotenv` is only installed in `backend/.venv`, but
this script runs under whatever `python` is on `PATH`) and pass it into the subprocess
environment.

**Scripts documented as `python scripts/<name>.py` failed under the system Python.**
`scripts/seed.py`'s documented command (`python scripts/seed.py`) reproducibly failed with
`ModuleNotFoundError: No module named 'pydantic_settings'` — the script imports
`backend/app` code, which is only installed in `backend/.venv`, but nothing made it actually
run under that interpreter. Fixed by adding `scripts/_bootstrap.py`, a shared helper that
re-execs a script under `backend/.venv`'s Python if it isn't already running there — wired
into `seed.py` and all three new scripts.

**A third, narrower issue found during testing, also fixed:** `getpass.getpass()` hangs
indefinitely in Git Bash (mintty doesn't provide the native Windows console `getpass` reads
from) rather than erroring — `onboard.py`'s password prompt now detects this (`MSYSTEM` env
var) and falls back to visible input with a printed warning, rather than leaving an operator
staring at an unresponsive terminal with no explanation.

None of these were hypothetical — each was reproduced by actually running the documented
command against a real environment, then fixed, then re-verified.

---

## 3. Verification performed

Against a real, freshly-initialized embedded Postgres instance (not a mock, not the test
suite's own isolated fixtures):

1. `python scripts/check_env.py` — correctly reported Database/Migrations/Plugin-catalog
   failures before setup steps were complete, and correctly reported Redis as unreachable
   (genuinely true in the verification environment) with an accurate, actionable hint — the
   failure-path behavior is exactly as important to verify as the success path.
2. `python scripts/migrate.py` — ran every migration successfully against the real instance
   once the `.env`-loading bug (§2) was fixed.
3. `python scripts/check_env.py` again — all checks passed except Redis (genuinely
   unavailable in the verification sandbox) and the two credential warnings (expected without
   real Reddit/Anthropic keys).
4. `python scripts/seed.py` — created a demo org/user against the real, migrated database.
5. `python scripts/onboard.py` — full interactive run (org name, slug, email, name, password
   with confirmation, project name, slug) against the real database, producing a real
   organization/user/project with the exact next-step output this report's §1 describes.
6. `python scripts/status.py` (and `--project <slug>`) — correctly showed the
   onboarding-created project with zero connections/configs/runs (accurate — none were made),
   and correctly reported the event-dispatch backlog as empty.
7. `ruff check scripts/` — clean on every new/modified file (one pre-existing, unrelated
   finding in `new_plugin.py`, not touched this phase). `python -m py_compile` clean on all six
   touched/added script files.

---

## 4. What is explicitly still not verified

Consistent with `ROADMAP.md`'s own long-standing caveat and `docs/reviews/
PRODUCTION_HARDENING_REPORT.md`'s remaining risks — this phase closes the *tooling* gap, not
the *real-external-service* gap:

- No real Reddit account has ever been connected via this project's OAuth flow outside of
  mocked/contract tests.
- No real Anthropic API call has ever drafted a real reply outside of mocked-transport tests.
- The full six-process stack (backend + scheduler + 4 workers) has never been started
  simultaneously and left running against real traffic — each process's *code* is tested in
  isolation (400 tests) and the *tooling* around starting them is now documented precisely,
  but the live, concurrent, multi-process runtime hasn't been observed end to end.
- The Docker Compose deployment path remains unverified, as it has been since Phase 1 — this
  phase did not attempt to change that, consistent with the operator's stated preference for
  the non-Docker path (`docs/beta/DEPLOYMENT_GUIDE.md`).

**This is exactly what `docs/beta/FIRST_RUN_CHECKLIST.md` and `docs/beta/BETA_TEST_PLAN.md`
exist to walk through next** — this report certifies the tooling and documentation are ready
for that first real run, not that the first real run has already happened.

---

## 5. How the deliverables fit together

| Document | Answers |
|---|---|
| `docs/beta/SETUP_GUIDE.md` | "How do I get this running on my machine, narratively, once?" |
| `docs/beta/FIRST_RUN_CHECKLIST.md` | "What's the literal, checkable sequence of commands?" |
| `docs/beta/DEPLOYMENT_GUIDE.md` | "How do I run this so it stays up, and what must I do before leaving it unattended?" |
| `docs/beta/TROUBLESHOOTING_GUIDE.md` | "Something's broken — what do I check?" |
| `docs/beta/KNOWN_LIMITATIONS.md` | "What should I NOT expect this to do, or watch out for?" |
| `docs/beta/BETA_TEST_PLAN.md` | "How much should I trust this, and when?" |
| `docs/examples/` | "What exactly do I send to configure X?" |
| `scripts/check_env.py`, `status.py`, `onboard.py` | The tools that make the above actionable rather than just descriptive. |

---

## 6. Recommendation

**Ready for Internal Beta**, with the explicit understanding that "internal beta" means one
operator, real accounts, close supervision, and full manual approval of every published
item — exactly the posture `docs/beta/BETA_TEST_PLAN.md` recommends and `ROADMAP.md`'s
non-goals permanently require regardless of phase. This is a materially different, lower bar
than "production ready for arbitrary users," which `docs/reviews/PRODUCTION_HARDENING_REPORT.md`
§4 already lists real, unaddressed gaps against (session revocation, role-based access,
automated backups, a CI pipeline) — none of which block one careful operator running this
against their own accounts, all of which matter more the moment that stops being true.

**Recommended next action:** follow `docs/beta/FIRST_RUN_CHECKLIST.md` yourself, start to
finish, against a real Reddit account and a real Anthropic key. That is the one thing no
amount of tooling or documentation in this phase could verify on its own — only a real run
can.
