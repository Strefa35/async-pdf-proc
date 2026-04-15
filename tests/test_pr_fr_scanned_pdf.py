"""PR-FR-3: documented behavior for pages with no PyPDF text (typical of many scans)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app import main as main_mod  # noqa: E402

# Minimal one-page PDF with no text operators (PyPDF yields empty strings).
BLANK_PAGE_PDF = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f 
0000000010 00000 n 
0000000053 00000 n 
0000000102 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
178
%%EOF"""


@pytest.mark.unit
def test_blank_page_pdf_has_no_pypdf_text() -> None:
    r = PdfReader(io.BytesIO(BLANK_PAGE_PDF))
    assert len(r.pages) == 1
    assert (r.pages[0].extract_text() or "").strip() == ""


@pytest.mark.unit
def test_extract_page_texts_returns_empty_strings_for_blank_pdf() -> None:
    texts = main_mod._extract_page_texts_from_pdf(BLANK_PAGE_PDF)
    assert texts == [""]
