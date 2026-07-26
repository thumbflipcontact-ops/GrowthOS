#!/usr/bin/env python3
"""Runs Alembic migrations against DATABASE_URL (from the environment or backend/../.env).
See scripts/README.md and docs/database/SCHEMA.md.

Run: python scripts/migrate.py [alembic-args...]
Examples:
  python scripts/migrate.py                  # upgrade to head
  python scripts/migrate.py downgrade -1
  python scripts/migrate.py revision --autogenerate -m "add companies.notes"
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


def _venv_python() -> Path:
    windows = BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    posix = BACKEND_DIR / ".venv" / "bin" / "python"
    if windows.exists():
        return windows
    if posix.exists():
        return posix
    raise SystemExit("backend/.venv not found — run `python scripts/setup.py` first.")


def _parse_dotenv(path: Path) -> dict[str, str]:
    """A minimal, dependency-free .env parser — `python-dotenv` is a backend/.venv-only
    dependency, but this script runs under whatever `python` is on PATH (see
    scripts/_bootstrap.py's docstring for the same class of problem), so it can't assume
    python-dotenv is importable here. Handles `KEY=value` lines, `#` comments, blank lines,
    and optional surrounding quotes — deliberately not a full .env spec implementation, just
    enough for this project's own `.env.example` shape."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #", 1)[0].strip()  # allow a trailing "# comment"
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _env_with_dotenv_loaded() -> dict[str, str]:
    """Alembic's own env.py (backend/migrations/env.py) reads DATABASE_URL straight from
    os.environ — it does not load .env itself (only the app's pydantic-settings Settings
    object does that, and this script invokes a plain `alembic` subprocess, not the app). So
    this script has to load .env into the subprocess's environment itself, or DATABASE_URL
    silently falls back to alembic.ini's placeholder and every migration fails with a
    confusing "Can't load plugin: sqlalchemy.dialects:driver" error — this was a real,
    reproduced bug, not a hypothetical one."""
    env = dict(os.environ)
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for key, value in _parse_dotenv(env_file).items():
            env.setdefault(key, value)  # real shell env vars still win over .env
    return env


def main() -> None:
    args = sys.argv[1:] or ["upgrade", "head"]
    python = _venv_python()
    alembic = python.parent / ("alembic.exe" if python.name.endswith(".exe") else "alembic")
    cmd = [str(alembic), *args]
    print(f"$ {' '.join(cmd)}  (cwd={BACKEND_DIR})")
    subprocess.run(cmd, check=True, cwd=BACKEND_DIR, env=_env_with_dotenv_loaded())


if __name__ == "__main__":
    main()
