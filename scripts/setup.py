#!/usr/bin/env python3
"""First-time local setup — no Docker required. See scripts/README.md and
docs/deployment/DEPLOYMENT.md.

1. Creates backend/.venv with Python 3.12 via uv (pgserver, this project's embedded-Postgres
   test/dev dependency, has no Python 3.13 Windows wheel yet — see
   docs/testing/TESTING.md).
2. Installs backend dependencies (incl. dev extras).
3. Copies .env.example to .env if it doesn't already exist.

Run: python scripts/setup.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


def run(cmd: list[str], **kwargs: object) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)  # type: ignore[arg-type]


def main() -> None:
    if shutil.which("uv") is None:
        print("Installing uv (Python toolchain/venv manager)...")
        run([sys.executable, "-m", "pip", "install", "uv"])

    print("Ensuring Python 3.12 is available (via uv)...")
    run(["uv", "python", "install", "3.12"])

    venv_dir = BACKEND_DIR / ".venv"
    if not venv_dir.exists():
        print("Creating backend/.venv (Python 3.12)...")
        run(["uv", "venv", "--python", "3.12", str(venv_dir)], cwd=BACKEND_DIR)

    print("Installing backend dependencies...")
    run(["uv", "pip", "install", "-e", ".[dev]", "--python", str(venv_dir)], cwd=BACKEND_DIR)

    env_file = REPO_ROOT / ".env"
    env_example = REPO_ROOT / ".env.example"
    if not env_file.exists():
        print("Creating .env from .env.example — fill in real values before running the app.")
        shutil.copyfile(env_example, env_file)
    else:
        print(".env already exists, leaving it alone.")

    print(
        "\nSetup complete.\n"
        "Next steps:\n"
        "  1. Edit .env with real values (or leave placeholders for local dev against the\n"
        "     embedded test Postgres — see scripts/dev_postgres.py / backend/scripts/dev_postgres.py).\n"
        "  2. python scripts/migrate.py\n"
        "  3. python scripts/lint.py\n"
        "  4. cd backend && .venv/Scripts/python -m pytest -p no:cov   (Windows)\n"
        "     cd backend && .venv/bin/python -m pytest -p no:cov      (macOS/Linux)\n"
    )


if __name__ == "__main__":
    main()
