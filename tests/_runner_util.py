"""Shared venv + pytest invocation for CLI runners (run_pytest.py, run_fr_tests.py)."""

from __future__ import annotations

import hashlib
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

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


def _marker_expr(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1].strip().lower()
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:].strip().lower()
        if arg.startswith("--markexpr="):
            return arg.split("=", 1)[1].strip().lower()
    return None


def _is_truthy_env(name: str) -> bool:
    val = os.environ.get(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _tcp_reachable(base_url: str, timeout_s: float = 1.5) -> tuple[bool, str]:
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port
    if not host:
        return False, f"invalid URL: {base_url}"
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True, ""
    except OSError as exc:
        return False, f"{host}:{port} not reachable ({exc})"


def _docker_reachable() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            check=False,
        )
    except FileNotFoundError:
        return False, "docker command not found"
    except OSError as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, ""
    msg = (proc.stderr or "").strip()
    return False, msg or "docker daemon unavailable"


def _print_preflight_errors(errors: list[str], *, context: str, include_unit_hint: bool) -> int:
    print(f"\n[preflight] Refusing to run {context} because required services are unavailable.", file=sys.stderr)
    for err in errors:
        print(f"[preflight] - {err}", file=sys.stderr)
    print("[preflight] Fixes:", file=sys.stderr)
    print("[preflight]   - start stack: docker compose up -d --build", file=sys.stderr)
    print("[preflight]   - if Docker is unavailable: SKIP_STREAMS_TESTS=1 or -m 'not streams'", file=sys.stderr)
    if include_unit_hint:
        print("[preflight]   - for unit-only checks: -m unit", file=sys.stderr)
    return 2


def run_pytest_preflight(argv: list[str]) -> int:
    marker_expr = _marker_expr(argv)
    errors: list[str] = []

    should_check_http = True
    should_check_streams = True
    if marker_expr is not None:
        has_not_unit = bool(re.search(r"\bnot\s+unit\b", marker_expr))
        has_integrationish = bool(re.search(r"\b(integration|smoke|fr[1-7]|multi)\b", marker_expr))
        has_unit = bool(re.search(r"\bunit\b", marker_expr))
        if has_unit and not has_integrationish:
            should_check_http = False
        should_check_streams = bool(re.search(r"\bstreams\b", marker_expr)) or has_not_unit
        if re.search(r"\bnot\s+streams\b", marker_expr):
            should_check_streams = False

    if _is_truthy_env("SKIP_STREAMS_TESTS"):
        should_check_streams = False

    if should_check_http:
        backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
        ok_backend, why_backend = _tcp_reachable(backend_url)
        ok_frontend, why_frontend = _tcp_reachable(frontend_url)
        if not ok_backend:
            errors.append(f"backend preflight failed for BACKEND_URL={backend_url}: {why_backend}")
        if not ok_frontend:
            errors.append(f"frontend preflight failed for FRONTEND_URL={frontend_url}: {why_frontend}")

    if should_check_streams:
        ok_docker, why_docker = _docker_reachable()
        if not ok_docker:
            errors.append(f"streams preflight failed (Docker required by Testcontainers): {why_docker}")

    if not errors:
        return 0
    return _print_preflight_errors(errors, context="pytest", include_unit_hint=True)


def run_fr_preflight(order: list[str], pytest_tail: list[str]) -> int:
    errors: list[str] = []

    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    ok_backend, why_backend = _tcp_reachable(backend_url)
    ok_frontend, why_frontend = _tcp_reachable(frontend_url)
    if not ok_backend:
        errors.append(f"backend preflight failed for BACKEND_URL={backend_url}: {why_backend}")
    if not ok_frontend:
        errors.append(f"frontend preflight failed for FRONTEND_URL={frontend_url}: {why_frontend}")

    lower_tail = " ".join(pytest_tail).lower()
    tail_selects_streams = bool(re.search(r"\bstreams\b", lower_tail)) and not bool(
        re.search(r"\bnot\s+streams\b", lower_tail)
    )
    needs_streams = ("fr3" in set(order)) or tail_selects_streams
    if needs_streams and not _is_truthy_env("SKIP_STREAMS_TESTS"):
        ok_docker, why_docker = _docker_reachable()
        if not ok_docker:
            errors.append(f"streams preflight failed (Docker required by Testcontainers): {why_docker}")

    if not errors:
        return 0
    return _print_preflight_errors(errors, context="FR pytest tags", include_unit_hint=False)
