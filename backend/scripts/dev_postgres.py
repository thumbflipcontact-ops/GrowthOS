"""Run a local, real (embedded) Postgres instance for development — no Docker required.

This is a convenience for developers who don't have Docker running locally; the Docker-based
path in docker/ (docker-compose.yml's `postgres` service, the real `pgvector/pgvector:pg16`
image) remains the documented, unchanged production-shaped option — see docker/README.md.
Prints DATABASE_URL to stdout, then stays running until interrupted (Ctrl+C).
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

import pgserver

DATA_DIR = Path(__file__).resolve().parent.parent / ".devdata" / "pgdata"


def main() -> None:
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    db = pgserver.get_server(str(DATA_DIR))
    # pgserver's default database is "postgres" — fine for local dev/test use; production
    # targets a real "growthos" database on a real Postgres server per docker-compose.yml.
    url = db.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
    print(f"DATABASE_URL={url}", flush=True)
    print("Postgres is running. Press Ctrl+C to stop.", flush=True)

    running = True

    def _stop(_sig: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    while running:
        time.sleep(0.5)

    db.cleanup()
    print("Postgres stopped.", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
