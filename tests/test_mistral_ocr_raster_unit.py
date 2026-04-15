"""Unit tests for mistral-ocr rasterization (PR-FR-5)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app import main as main_mod  # noqa: E402


def _minimal_two_page_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=72, height=72)
    w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.mark.unit
def test_rasterize_pdf_pages_produces_pngs() -> None:
    pdf = _minimal_two_page_pdf()
    pngs = main_mod._rasterize_pdf_pages_to_png_bytes(pdf)
    assert len(pngs) == 2
    assert all(p[:8] == b"\x89PNG\r\n\x1a\n" for p in pngs)
