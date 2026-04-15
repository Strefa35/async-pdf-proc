"""FR-1: multi-file upload + parser in request."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import sync_parser_all, sync_results_len
from tests.support.http_api import post_pdf_extract
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr1]


def test_fr1_multi_upload_same_file_twice(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf, pdf], parser="pypdf")
    r.raise_for_status()
    data = r.json()
    assert sync_results_len(data, 2), data
    assert sync_parser_all(data, "pypdf"), data
