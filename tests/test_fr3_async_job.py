"""FR-3: async job submit + poll until done."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import job_result_ok
from tests.support.http_api import get_job, poll_job_until_done, post_jobs_extract, submit_job_id
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr3]


def test_fr3_async_extract_job_completes(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    sub = post_jobs_extract(http_client, backend_url, [pdf], parser="pypdf")
    job_id = submit_job_id(sub)
    assert job_id, sub.text

    q = get_job(http_client, backend_url, job_id)
    q.raise_for_status()
    qst = str(q.json().get("status") or "")
    assert qst in ("queued", "processing", "done"), q.json()

    status, final = poll_job_until_done(http_client, backend_url, job_id, max_attempts=45, interval_s=1.0)
    assert status == "done", final
    assert job_result_ok(final), final
