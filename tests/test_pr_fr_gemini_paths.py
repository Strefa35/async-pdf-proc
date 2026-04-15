"""PR-FR-2: Gemini native PDF path must not silently fall back to text-only formatting."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app import main as main_mod  # noqa: E402


def _install_generate_content_mock(markdown: str) -> MagicMock:
    model = MagicMock()
    resp = MagicMock()
    resp.text = markdown
    model.generate_content.return_value = resp
    return model


@pytest.mark.unit
@patch.object(main_mod, "GOOGLE_API_KEY", "test-key")
@patch.object(main_mod, "genai")
def test_gemini_native_pdf_sends_inline_application_pdf(mock_genai: MagicMock) -> None:
    mock_genai.GenerativeModel.return_value = _install_generate_content_mock("<!-- PAGE 1 -->\n# Hi")

    out = main_mod._extract_markdown_with_gemini_native_pdf(
        b"%PDF-1.4 minimal",
        filename="doc.pdf",
        expected_pages=1,
    )
    assert "PAGE 1" in out
    mock_genai.GenerativeModel.assert_called_once()
    args, _kwargs = mock_genai.GenerativeModel.return_value.generate_content.call_args
    contents = args[0]
    assert isinstance(contents, list), contents
    first = contents[0]
    assert isinstance(first, dict)
    inline = first.get("inline_data") or {}
    assert inline.get("mime_type") == "application/pdf"
    assert inline.get("data") == b"%PDF-1.4 minimal"


@pytest.mark.unit
@patch.object(main_mod, "GOOGLE_API_KEY", "test-key")
@patch.object(main_mod, "genai")
def test_gemini_text_formatter_does_not_send_inline_pdf(mock_genai: MagicMock) -> None:
    mock_genai.GenerativeModel.return_value = _install_generate_content_mock("<!-- PAGE 1 -->\nok")

    main_mod._extract_markdown_with_gemini(
        b"%PDF-ignored",
        filename="doc.pdf",
        page_texts=["hello"],
    )
    args, _kwargs = mock_genai.GenerativeModel.return_value.generate_content.call_args
    payload = args[0]
    assert isinstance(payload, str), "Formatter path must be text-only prompt (no silent PDF multimodal)."
    assert "hello" in payload
    assert "inline_data" not in payload
    assert "application/pdf" not in payload


@pytest.mark.unit
def test_gemini_native_pdf_rejects_oversized_inline_payload() -> None:
    with (
        patch.object(main_mod, "GOOGLE_API_KEY", "test-key"),
        patch.object(main_mod, "_gemini_inline_pdf_max_bytes", return_value=8),
    ):
        with pytest.raises(HTTPException) as ei:
            main_mod._extract_markdown_with_gemini_native_pdf(
                b"1234567890",
                filename="big.pdf",
                expected_pages=1,
            )
    assert ei.value.status_code == 413


@pytest.mark.unit
def test_gemini_generate_content_passes_sdk_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: HTTP deadline must be set on the SDK call, not only asyncio.wait_for."""
    pytest.importorskip("google.generativeai.types")
    from google.generativeai.types import RequestOptions

    monkeypatch.setattr(main_mod, "GEMINI_CALL_TIMEOUT_SECONDS", 77.0)
    model = MagicMock()
    model.generate_content.return_value = MagicMock(text="ok")

    main_mod._gemini_generate_content(model, "prompt")

    model.generate_content.assert_called_once()
    _args, kwargs = model.generate_content.call_args
    assert kwargs.get("request_options") is not None
    ro = kwargs["request_options"]
    assert isinstance(ro, RequestOptions)
    assert ro.timeout == 77.0


@pytest.mark.unit
def test_gemini_blocking_executor_shares_pdf_pool_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_POOL_MAX_WORKERS", raising=False)
    try:
        main_mod._shutdown_blocking_executor()
        pdf = main_mod._get_pdf_cpu_executor()
        gem = main_mod._get_gemini_blocking_executor()
        assert pdf is gem
    finally:
        main_mod._shutdown_blocking_executor()


@pytest.mark.unit
def test_gemini_blocking_executor_isolated_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_POOL_MAX_WORKERS", "2")
    try:
        main_mod._shutdown_blocking_executor()
        pdf = main_mod._get_pdf_cpu_executor()
        gem = main_mod._get_gemini_blocking_executor()
        assert pdf is not gem
    finally:
        monkeypatch.delenv("GEMINI_POOL_MAX_WORKERS", raising=False)
        main_mod._shutdown_blocking_executor()
