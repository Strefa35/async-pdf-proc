"""Pytest configuration: live stack URLs, PDF discovery, shared HTTP client."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest


def _collect_pdf_paths() -> list[Path]:
    single = os.environ.get("PDF_FILE", "").strip()
    root = Path(__file__).resolve().parent
    fixture_dir = root / "fixtures" / "pdf"
    if single:
        p = Path(single)
        return [p.resolve()] if p.is_file() else []
    if not fixture_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(fixture_dir.iterdir()):
        if p.is_file() and p.suffix.lower() == ".pdf":
            out.append(p)
    return out


def pytest_configure(config: pytest.Config) -> None:
    # Used by pytest_generate_tests for parametrized pdf_path.
    setattr(config, "pdf_fixture_paths", _collect_pdf_paths())


@pytest.fixture(scope="session")
def backend_url() -> str:
    return os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


@pytest.fixture(scope="session")
def frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")


@pytest.fixture(scope="session")
def http_client() -> Generator[httpx.Client, None, None]:
    timeout = float(os.environ.get("E2E_HTTP_TIMEOUT", "180"))
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        yield client


@pytest.fixture(scope="session")
def all_pdf_paths(pytestconfig: pytest.Config) -> list[Path]:
    return list(getattr(pytestconfig, "pdf_fixture_paths", []) or [])


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "pdf_path" not in metafunc.fixturenames:
        return
    paths: list[Path] = list(getattr(metafunc.config, "pdf_fixture_paths", []) or [])
    if not paths:
        metafunc.parametrize("pdf_path", [pytest.param(None, id="NO_PDF")])
    else:
        metafunc.parametrize("pdf_path", paths, ids=lambda p: p.name if p else "none")
