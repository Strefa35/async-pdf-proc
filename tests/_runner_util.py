"""Shared venv + pytest invocation for CLI runners (run_pytest.py, run_fr_tests.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
REQUIREMENTS = TESTS_DIR / "requirements-pytest.txt"
DEFAULT_VENV = PROJECT_ROOT / ".pytest-venv"


def venv_python() -> Path:
    venv = Path(os.environ.get("PYTEST_VENV", DEFAULT_VENV))
    return venv / "bin" / "python"


def ensure_venv() -> Path:
    """Create local venv if missing and install tests/requirements-pytest.txt."""
    py = venv_python()
    venv_dir = py.parent.parent
    if not py.is_file():
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)], cwd=PROJECT_ROOT)
    pip = venv_dir / "bin" / "pip"
    subprocess.check_call([str(pip), "install", "-q", "-r", str(REQUIREMENTS)], cwd=PROJECT_ROOT)
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
