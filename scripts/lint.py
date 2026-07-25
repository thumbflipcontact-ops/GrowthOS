#!/usr/bin/env python3
"""Runs the same checks CI runs: ruff (lint) and mypy --strict (type check) against
backend/app/, plus ruff against agents/ and plugins/. See scripts/README.md and
CONTRIBUTING.md "Code style".

Run: python scripts/lint.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


def _venv_bin(name: str) -> Path:
    windows = BACKEND_DIR / ".venv" / "Scripts" / f"{name}.exe"
    posix = BACKEND_DIR / ".venv" / "bin" / name
    if windows.exists():
        return windows
    if posix.exists():
        return posix
    raise SystemExit(f"{name} not found in backend/.venv — run `python scripts/setup.py` first.")


def main() -> None:
    ruff = _venv_bin("ruff")
    mypy = _venv_bin("mypy")

    failed = False
    for cmd, cwd in [
        ([str(ruff), "check", "."], BACKEND_DIR),
        ([str(mypy), "app"], BACKEND_DIR),
    ]:
        print(f"$ {' '.join(cmd)}  (cwd={cwd})")
        result = subprocess.run(cmd, cwd=cwd)
        failed = failed or result.returncode != 0

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
