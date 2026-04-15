from __future__ import annotations

from pathlib import Path

import pytest


def require_pdf(pdf_path: Path | None) -> Path:
    if pdf_path is None:
        pytest.skip("No PDF fixtures: run python3 tests/download_pdf_fixtures.py or set PDF_FILE")
    if not pdf_path.is_file():
        pytest.skip(f"Missing PDF file: {pdf_path}")
    return pdf_path
