"""Shared venv + pytest invocation for CLI runners (run_pytest.py, run_fr_tests.py)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REQUIREMENTS = TESTS_DIR / "requirements-pytest.txt"
DEFAULT_VENV = PROJECT_ROOT / ".pytest-venv"
# Written after a successful `pip install -r`; compared to current requirements hash.
_REQUIREMENTS_SENTINEL = ".requirements-pytest.sha256"


def venv_python() -> Path:
    venv = Path(os.environ.get("PYTEST_VENV", DEFAULT_VENV))
    return venv / "bin" / "python"


def _requirements_fingerprint() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_venv() -> Path:
    """Create local venv if missing; install requirements only when venv is new or they changed."""
    py = venv_python()
    venv_dir = py.parent.parent
    created = False
    if not py.is_file():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)], cwd=PROJECT_ROOT)
        created = True

    fingerprint = _requirements_fingerprint()
    sentinel = venv_dir / _REQUIREMENTS_SENTINEL
    need_install = created
    if not need_install:
        if not sentinel.is_file():
            need_install = True
        else:
            try:
                stored = sentinel.read_text(encoding="utf-8").strip()
            except OSError:
                need_install = True
            else:
                need_install = stored != fingerprint

    if need_install:
        pip = venv_dir / "bin" / "pip"
        subprocess.check_call([str(pip), "install", "-q", "-r", str(REQUIREMENTS)], cwd=PROJECT_ROOT)
        sentinel.write_text(fingerprint + "\n", encoding="utf-8")
    return py


def default_report_args() -> list[str]:
    REPORT_DIR = TESTS_DIR / "report"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return [
        f"--junitxml={REPORT_DIR / 'junit.xml'}",
        f"--html={REPORT_DIR / 'report.html'}",
        "--self-contained-html",
    ]


def run_pytest(extra_args: list[str], *, env: dict[str, str] | None = None) -> int:
    py = ensure_venv()
    cmd = [str(py), "-m", "pytest", str(TESTS_DIR), *extra_args]
    return subprocess.call(cmd, cwd=PROJECT_ROOT, env=env)
