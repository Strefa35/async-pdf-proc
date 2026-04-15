"""End-to-end smoke checks (extract, parsers, cache, async job, Gemini answer)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import (
    any_result_cached_true,
    mistral_missing_key_response,
    sync_first_summary_nonempty,
    sync_first_timestamps_ok,
    sync_parser_all,
    sync_results_len,
)
from tests.support.http_api import poll_job_until_done, post_jobs_extract, post_pdf_extract, submit_job_id
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.smoke]


def test_smoke_single_and_multi_extract_summary_timestamps(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)

    single = post_pdf_extract(http_client, backend_url, [pdf])
    single.raise_for_status()
    ds = single.json()
    assert sync_results_len(ds, 1), ds
    assert sync_first_summary_nonempty(ds), ds
    assert sync_first_timestamps_ok(ds), ds

    multi = post_pdf_extract(http_client, backend_url, [pdf, pdf])
    multi.raise_for_status()
    dm = multi.json()
    assert sync_results_len(dm, 2), dm
    assert any_result_cached_true(dm), dm

    for parser in ("pypdf", "gemini-2.5-flash", "gemini-2.5-flash-text", "gemini-2.5-flash-pdf"):
        r = post_pdf_extract(http_client, backend_url, [pdf], parser=parser)
        r.raise_for_status()
        d = r.json()
        assert sync_parser_all(d, parser), d
        assert sync_first_summary_nonempty(d), d
        assert sync_first_timestamps_ok(d), d

    mr = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral")
    if mr.status_code >= 400 and mistral_missing_key_response(mr.text):
        pass
    else:
        mr.raise_for_status()
        assert sync_parser_all(mr.json(), "mistral"), mr.text

    mo = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral-ocr")
    if mo.status_code >= 400 and mistral_missing_key_response(mo.text):
        pass
    else:
        mo.raise_for_status()
        assert sync_parser_all(mo.json(), "mistral-ocr"), mo.text

    sub = post_jobs_extract(http_client, backend_url, [pdf], parser="pypdf")
    job_id = submit_job_id(sub)
    assert job_id, sub.text

    st, job = poll_job_until_done(http_client, backend_url, job_id, max_attempts=30, interval_s=1.0)
    assert st == "done", job
    res = job.get("result") or {}
    assert isinstance(res.get("text"), str) and res["text"].strip()
    assert isinstance(res.get("summary"), str) and res["summary"].strip()
    assert "content_generated_at" in res and "summary_generated_at" in res


def test_smoke_gemini_answer(http_client: httpx.Client, backend_url: str) -> None:
    r = http_client.post(
        f"{backend_url}/api/gemini/answer",
        json={"prompt": "Reply with exactly: OK", "language": "en"},
    )
    if r.status_code == 500 and "GOOGLE_API_KEY" in r.text:
        pytest.skip("GOOGLE_API_KEY not configured")
    r.raise_for_status()
    data = r.json()
    assert isinstance(data.get("model"), str)
    assert isinstance(data.get("text"), str) and data["text"].strip()
