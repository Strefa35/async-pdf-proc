"""HTTP helpers for integration tests (live backend + optional frontend)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx


def build_client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True)


def post_pdf_extract(
    client: httpx.Client,
    base_url: str,
    paths: list[Path],
    *,
    parser: str = "pypdf",
    language: str | None = None,
) -> httpx.Response:
    base = base_url.rstrip("/")
    data: dict[str, str] = {"parser": parser}
    if language is not None:
        data["language"] = language
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for p in paths:
        files.append(
            ("files", (p.name, p.read_bytes(), "application/pdf")),
        )
    return client.post(f"{base}/api/pdf/extract", data=data, files=files)


def post_jobs_extract(
    client: httpx.Client,
    base_url: str,
    paths: list[Path],
    *,
    parser: str = "pypdf",
    language: str | None = None,
) -> httpx.Response:
    base = base_url.rstrip("/")
    data: dict[str, str] = {"parser": parser}
    if language is not None:
        data["language"] = language
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for p in paths:
        files.append(
            ("files", (p.name, p.read_bytes(), "application/pdf")),
        )
    return client.post(f"{base}/api/jobs/extract", data=data, files=files)


def get_job(client: httpx.Client, base_url: str, job_id: str) -> httpx.Response:
    base = base_url.rstrip("/")
    return client.get(f"{base}/api/jobs/{job_id}")


def poll_job_until_done(
    client: httpx.Client,
    base_url: str,
    job_id: str,
    *,
    max_attempts: int = 45,
    interval_s: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """
    Poll GET /api/jobs/{id} until done, failed, or attempts exhausted.
    Returns (status, parsed_json).
    """
    base = base_url.rstrip("/")
    last: dict[str, Any] = {}
    for _ in range(max_attempts):
        r = client.get(f"{base}/api/jobs/{job_id}")
        r.raise_for_status()
        last = r.json()
        st = str(last.get("status") or "")
        if st == "done":
            return "done", last
        if st == "failed":
            return "failed", last
        time.sleep(interval_s)
    return "timeout", last


def submit_job_id(response: httpx.Response) -> str:
    response.raise_for_status()
    data = response.json()
    jobs = data.get("jobs") or []
    if not jobs or not isinstance(jobs[0], dict):
        return ""
    return str(jobs[0].get("job_id") or "")
