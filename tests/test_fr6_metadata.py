"""FR-6: timestamps, sha256, parser on sync result."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import sync_first_sha_parser, sync_first_timestamps_ok
from tests.support.http_api import post_pdf_extract
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr6]


def test_fr6_sync_timestamps_sha_parser(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf], parser="pypdf", language="en")
    r.raise_for_status()
    data = r.json()
    assert sync_first_timestamps_ok(data), data
    sha, parser = sync_first_sha_parser(data)
    assert sha and parser, data
