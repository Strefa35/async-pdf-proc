"""
Multi-PDF: one POST with every fixture PDF (sync /api/pdf/extract + async /api/jobs/extract).

Requires at least two PDFs under ``tests/fixtures/pdf/`` unless ``PDF_FILE`` pins a single path
(in which case these tests skip).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from tests.support.checks import job_result_ok, sync_parser_all, sync_results_len
from tests.support.http_api import poll_job_until_done, post_jobs_extract, post_pdf_extract, submit_job_id

pytestmark = [pytest.mark.integration, pytest.mark.multi]


def test_sync_all_fixtures_in_one_extract(
    http_client: httpx.Client,
    backend_url: str,
    all_pdf_paths: list[Path],
) -> None:
    if len(all_pdf_paths) < 2:
        pytest.skip("Need at least two PDFs under tests/fixtures/pdf/")
    r = post_pdf_extract(http_client, backend_url, all_pdf_paths, parser="pypdf")
    r.raise_for_status()
    data = r.json()
    n = len(all_pdf_paths)
    assert sync_results_len(data, n), data
    assert sync_parser_all(data, "pypdf"), data


def test_async_all_fixtures_in_one_jobs_extract(
    http_client: httpx.Client,
    backend_url: str,
    all_pdf_paths: list[Path],
) -> None:
    if len(all_pdf_paths) < 2:
        pytest.skip("Need at least two PDFs under tests/fixtures/pdf/")
    parser = os.environ.get("PARSER", "pypdf")
    sub = post_jobs_extract(
        http_client,
        backend_url,
        all_pdf_paths,
        parser=parser,
        language="en",
    )
    sub.raise_for_status()
    jobs = sub.json().get("jobs") or []
    assert len(jobs) == len(all_pdf_paths), sub.text

    for j in jobs:
        jid = str(j.get("job_id") or "")
        assert jid
        st, final = poll_job_until_done(
            http_client,
            backend_url,
            jid,
            max_attempts=120,
            interval_s=1.0,
        )
        assert st == "done", final
        assert job_result_ok(final), final
