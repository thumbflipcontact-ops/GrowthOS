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

Compose file and Dockerfiles are scaffolded to match the service topology in
`docs/deployment/DEPLOYMENT.md`; they reference `backend/` and `frontend/` application code
that hasn't been implemented yet (Phase 1, see `ROADMAP.md`) and will not successfully build
until that code exists.
