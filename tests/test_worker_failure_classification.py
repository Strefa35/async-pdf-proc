"""Unit tests for worker transient vs permanent failure classification (PR-TR-7)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.main import LlmCapacityExceededError  # noqa: E402
from app.worker import classify_job_failure  # noqa: E402


@pytest.mark.unit
def test_transient_http_503() -> None:
    transient, _ = classify_job_failure(HTTPException(status_code=503, detail="x"))
    assert transient is True


@pytest.mark.unit
def test_permanent_http_400() -> None:
    transient, _ = classify_job_failure(HTTPException(status_code=400, detail="bad"))
    assert transient is False


@pytest.mark.unit
def test_transient_llm_capacity() -> None:
    transient, _ = classify_job_failure(LlmCapacityExceededError(retry_after_s=5))
    assert transient is True


@pytest.mark.unit
def test_transient_asyncio_timeout() -> None:
    transient, _ = classify_job_failure(asyncio.TimeoutError())
    assert transient is True


@pytest.mark.unit
def test_transient_httpx_502() -> None:
    req = httpx.Request("GET", "https://example.invalid/")
    resp = httpx.Response(502, request=req)
    exc = httpx.HTTPStatusError("down", request=req, response=resp)
    transient, _ = classify_job_failure(exc)
    assert transient is True
