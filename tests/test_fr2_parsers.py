"""FR-2: parser selection (pypdf, Gemini pdf/text/legacy, mistral)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.support.checks import mistral_missing_key_response, sync_parser_all
from tests.support.http_api import post_pdf_extract
from tests.support.pdf_fixtures import require_pdf

pytestmark = [pytest.mark.integration, pytest.mark.fr2]


def test_fr2_pypdf_and_gemini_parser_reflected(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    for parser in ("pypdf", "gemini-2.5-flash", "gemini-2.5-flash-text", "gemini-2.5-flash-pdf"):
        r = post_pdf_extract(http_client, backend_url, [pdf], parser=parser)
        r.raise_for_status()
        data = r.json()
        assert sync_parser_all(data, parser), (parser, data)


def test_fr2_mistral_mock_or_key(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral")
    text = r.text
    if r.status_code >= 400 and mistral_missing_key_response(text):
        return
    r.raise_for_status()
    data = r.json()
    assert sync_parser_all(data, "mistral"), data


def test_fr2_mistral_ocr_mock_or_key(
    http_client: httpx.Client,
    backend_url: str,
    pdf_path: Path | None,
) -> None:
    pdf = require_pdf(pdf_path)
    r = post_pdf_extract(http_client, backend_url, [pdf], parser="mistral-ocr")
    text = r.text
    if r.status_code >= 400 and mistral_missing_key_response(text):
        return
    r.raise_for_status()
    data = r.json()
    assert sync_parser_all(data, "mistral-ocr"), data
