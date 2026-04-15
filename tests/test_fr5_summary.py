"""FR-5: non-empty summary (Gemini) on sync extract."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import sync_first_summary_nonempty
from tests.support.http_api import post_pdf_extract
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr5]


def test_fr5_sync_summary_nonempty(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf], parser="pypdf", language="en")
    r.raise_for_status()
    assert sync_first_summary_nonempty(r.json()), r.text
