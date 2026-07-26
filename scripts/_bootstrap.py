"""Shared helper for scripts/ entrypoints that import `backend/app` code directly (not via a
subprocess, unlike migrate.py's `alembic` invocation). `python scripts/<name>.py` resolves to
whatever `python` is first on PATH — usually a system Python, not `backend/.venv`'s — so a
script that does `from app.core.config import get_settings` fails with
`ModuleNotFoundError: No module named 'pydantic_settings'` (or similar) unless it's actually
running under `backend/.venv`'s interpreter, where that package (and everything else `app`
needs) is installed. This was a real, reproduced bug in scripts/seed.py, not a hypothetical
one — see docs/reviews/INTERNAL_BETA_READINESS_REPORT.md.

Call `ensure_running_under_backend_venv(__file__)` as the very first line of a script's
`if __name__ == "__main__":` block, before any `app.*` import — it re-execs the same script
under `backend/.venv`'s python if we're not already running under it, and does nothing
(returns immediately) if we already are.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _venv_python(repo_root: Path) -> Path:
    windows = repo_root / "backend" / ".venv" / "Scripts" / "python.exe"
    posix = repo_root / "backend" / ".venv" / "bin" / "python"
    if windows.exists():
        return windows
    if posix.exists():
        return posix
    raise SystemExit("backend/.venv not found — run `python scripts/setup.py` first.")


def ensure_running_under_backend_venv(script_path: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    venv_python = _venv_python(repo_root)

    if Path(sys.executable).resolve() == venv_python.resolve():
        return  # already running under the right interpreter — nothing to do

    result = subprocess.run([str(venv_python), script_path, *sys.argv[1:]])
    raise SystemExit(result.returncode)
