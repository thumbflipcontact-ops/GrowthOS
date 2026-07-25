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


def main() -> None:
    args = sys.argv[1:] or ["upgrade", "head"]
    python = _venv_python()
    alembic = python.parent / ("alembic.exe" if python.name.endswith(".exe") else "alembic")
    cmd = [str(alembic), *args]
    print(f"$ {' '.join(cmd)}  (cwd={BACKEND_DIR})")
    subprocess.run(cmd, check=True, cwd=BACKEND_DIR)


if __name__ == "__main__":
    main()
