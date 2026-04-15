"""
Broad integration sweep per fixture PDF (sync + async paths).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import (
    job_result_ok,
    job_result_pages_ok,
    job_result_sha_parser_ok,
    mistral_missing_key_response,
    sync_first_pages_ok,
    sync_first_sha_parser,
    sync_first_summary_nonempty,
    sync_first_timestamps_ok,
    sync_parser_all,
    sync_results_len,
)
from tests.support.http_api import get_job, poll_job_until_done, post_jobs_extract, post_pdf_extract, submit_job_id
from tests.support.pdf_fixtures import require_pdf

pytestmark = pytest.mark.integration


def test_integration_fr_sweep_per_pdf(
    http_client: httpx.Client,
    backend_url: str,
    frontend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)

    r1 = post_pdf_extract(http_client, backend_url, [pdf, pdf], parser="pypdf")
    r1.raise_for_status()
    d1 = r1.json()
    assert sync_results_len(d1, 2) and sync_parser_all(d1, "pypdf"), d1

    rs = post_pdf_extract(http_client, backend_url, [pdf], parser="pypdf", language="en")
    rs.raise_for_status()
    sync = rs.json()
    assert sync_first_pages_ok(sync), sync
    assert sync_first_summary_nonempty(sync), sync
    assert sync_first_timestamps_ok(sync), sync
    sha, parser = sync_first_sha_parser(sync)
    assert sha and parser, sync

    for parser in ("pypdf", "gemini-2.5-flash", "gemini-2.5-flash-text", "gemini-2.5-flash-pdf"):
        rp = post_pdf_extract(http_client, backend_url, [pdf], parser=parser)
        rp.raise_for_status()
        assert sync_parser_all(rp.json(), parser), rp.text

    rm = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral")
    if rm.status_code >= 400 and mistral_missing_key_response(rm.text):
        pass
    else:
        rm.raise_for_status()
        assert sync_parser_all(rm.json(), "mistral"), rm.text

    ro = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral-ocr")
    if ro.status_code >= 400 and mistral_missing_key_response(ro.text):
        pass
    else:
        ro.raise_for_status()
        assert sync_parser_all(ro.json(), "mistral-ocr"), ro.text

    sub = post_jobs_extract(http_client, backend_url, [pdf], parser="pypdf", language="en")
    job_id = submit_job_id(sub)
    assert job_id, sub.text

    q = get_job(http_client, backend_url, job_id)
    q.raise_for_status()
    assert str(q.json().get("status") or "") in ("queued", "processing", "done")

    st, final = poll_job_until_done(http_client, backend_url, job_id)
    assert st == "done", final
    assert job_result_ok(final), final
    assert job_result_pages_ok(final), final
    assert job_result_sha_parser_ok(final), final

    pr = http_client.get(f"{frontend_url}/api/jobs/{job_id}")
    if pr.status_code == 200 and str(pr.json().get("status") or "") != "done":
        # Same as bash: warn-only; do not fail the suite.
        pass
