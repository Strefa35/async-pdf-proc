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


@pytest.mark.unit
@patch.object(main_mod, "GOOGLE_API_KEY", "test-key")
@patch.object(main_mod, "_gemini_generate_content")
def test_gemini_native_pdf_sends_inline_application_pdf(mock_gc: MagicMock) -> None:
    pytest.importorskip("google.genai.types")
    mock_gc.return_value = MagicMock(text="<!-- PAGE 1 -->\n# Hi")

    out = main_mod._extract_markdown_with_gemini_native_pdf(
        b"%PDF-1.4 minimal",
        filename="doc.pdf",
        expected_pages=1,
    )
    assert "PAGE 1" in out
    mock_gc.assert_called_once()
    contents = mock_gc.call_args[0][0]
    assert isinstance(contents, list), contents
    assert len(contents) == 2
    first = contents[0]
    inline = getattr(first, "inline_data", None)
    assert inline is not None
    assert inline.mime_type == "application/pdf"
    assert inline.data == b"%PDF-1.4 minimal"


@pytest.mark.unit
@patch.object(main_mod, "GOOGLE_API_KEY", "test-key")
@patch.object(main_mod, "_gemini_generate_content")
def test_gemini_text_formatter_does_not_send_inline_pdf(mock_gc: MagicMock) -> None:
    mock_gc.return_value = MagicMock(text="<!-- PAGE 1 -->\nok")

    main_mod._extract_markdown_with_gemini(
        b"%PDF-ignored",
        filename="doc.pdf",
        page_texts=["hello"],
    )
    mock_gc.assert_called_once()
    payload = mock_gc.call_args[0][0]
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
    """Regression: HTTP deadline must be set on the SDK client, not only asyncio.wait_for."""
    pytest.importorskip("google.genai.types")
    from google.genai import types as sdk_types

    monkeypatch.setattr(main_mod, "GEMINI_CALL_TIMEOUT_SECONDS", 77.0)
    monkeypatch.setattr(main_mod, "GOOGLE_API_KEY", "test-key")

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(text="ok")

    with patch.object(main_mod.google_genai, "Client", return_value=mock_client) as mock_client_cls:
        main_mod._gemini_generate_content("prompt")

    mock_client_cls.assert_called_once()
    _args, kwargs = mock_client_cls.call_args
    assert kwargs.get("http_options") is not None
    ho = kwargs["http_options"]
    assert isinstance(ho, sdk_types.HttpOptions)
    assert ho.timeout == 77_000
    mock_client.models.generate_content.assert_called_once()


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
