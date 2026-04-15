"""Async API edge cases (no PDF fixtures)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_unknown_job_returns_404(http_client: httpx.Client, backend_url: str) -> None:
    r = http_client.get(f"{backend_url}/api/jobs/ffffffffffffffffffffffffffffffff")
    assert r.status_code == 404


def test_empty_file_job_returns_400(http_client: httpx.Client, backend_url: str) -> None:
    files = {"files": ("empty.pdf", b"", "application/pdf")}
    data = {"parser": "pypdf"}
    r = http_client.post(f"{backend_url}/api/jobs/extract", data=data, files=files)
    assert r.status_code == 400


def test_jobs_extract_without_files_returns_400_or_422(http_client: httpx.Client, backend_url: str) -> None:
    data = {"parser": "pypdf"}
    r = http_client.post(f"{backend_url}/api/jobs/extract", data=data)
    assert r.status_code in (400, 422), r.text
