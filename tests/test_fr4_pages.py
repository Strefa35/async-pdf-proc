"""FR-4: pages[] in sync response."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import sync_first_pages_ok
from tests.support.http_api import post_pdf_extract
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr4]


def test_fr4_sync_pages_nonempty(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf], parser="pypdf")
    r.raise_for_status()
    assert sync_first_pages_ok(r.json()), r.text
