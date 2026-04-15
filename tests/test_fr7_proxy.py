"""FR-7: poll job + optional frontend proxy."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import job_result_ok
from tests.support.http_api import poll_job_until_done, post_jobs_extract, submit_job_id
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr7]


def test_fr7_job_poll_and_optional_frontend_proxy(
    http_client: httpx.Client,
    backend_url: str,
    frontend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    sub = post_jobs_extract(http_client, backend_url, [pdf], parser="pypdf", language="en")
    job_id = submit_job_id(sub)
    assert job_id, sub.text

    status, final = poll_job_until_done(http_client, backend_url, job_id)
    assert status == "done", final
    assert job_result_ok(final), final

    pr = http_client.get(f"{frontend_url}/api/jobs/{job_id}")
    if pr.status_code != 200:
        pytest.skip(f"frontend proxy not reachable: HTTP {pr.status_code}")
    proxy_st = str(pr.json().get("status") or "")
    if proxy_st != "done":
        pytest.skip(f"frontend proxy status={proxy_st!r} (backend job OK; same tolerance as bash WARN)")
