# Docker

Local development and production run the same Compose topology — see
`docs/deployment/DEPLOYMENT.md` for environment-by-environment detail and the reasoning for
Docker Compose over Kubernetes at this stage.

```
docker/
├── docker-compose.yml       Full local stack: backend, frontend, three worker pools
│                              (agents, events, publish), scheduler, postgres, redis
├── Dockerfile.backend        Shared base for backend, workers, scheduler
├── Dockerfile.frontend       Next.js build
└── Dockerfile.worker         Arq worker entrypoint, built FROM the backend image — used by
                                worker-agents, worker-events, and worker-publish alike
```

## Usage

```bash
cp ../.env.example ../.env    # fill in real values
docker compose -f docker-compose.yml up --build
```

## Status

`backend/` is implemented (Phase 1 platform foundation — see `ARCHITECTURE_FREEZE.md` and
`ROADMAP.md`) and the Dockerfiles/compose file reference its real module paths
(`app.jobs.*.WorkerSettings`, `app.scheduler`), but **this Docker setup has not itself been
built or run** — Phase 1 implementation used a Docker-free local workflow instead (see
`scripts/README.md` and `backend/scripts/dev_postgres.py`), per explicit instruction. Treat
this as unverified until someone runs `docker compose up --build` end to end and fixes
whatever Docker-specific issue surfaces (there is usually at least one). `frontend/` has no
code yet at all (Phase 2).
