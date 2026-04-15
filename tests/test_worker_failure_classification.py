"""Unit tests for worker transient vs permanent failure classification (PR-TR-7)."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.main import (  # noqa: E402
    REDIS_CONSUMER_GROUP,
    REDIS_STREAM_NAME,
    LlmCapacityExceededError,
    _blob_b64_key,
    _job_key,
)
from app.worker import _handle_one_delivery, _safe_xack, classify_job_failure  # noqa: E402


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(RedisConnectionError("connection lost"), id="redis_connection"),
        pytest.param(RedisTimeoutError("command timed out"), id="redis_timeout"),
        pytest.param(asyncio.TimeoutError(), id="asyncio_timeout"),
        pytest.param(OSError(11, "Resource temporarily unavailable"), id="oserror"),
        pytest.param(ConnectionError("connection reset"), id="builtin_connection"),
    ],
)
def test_safe_xack_swallows_transient_transport_errors(exc: BaseException) -> None:
    """ACK must not take down the consumer loop on timeouts / connection loss."""
    redis = MagicMock()
    redis.xack = AsyncMock(side_effect=exc)

    async def run() -> None:
        await _safe_xack(redis, "99-0")

    asyncio.run(run())
    redis.xack.assert_awaited_once()


@pytest.mark.unit
def test_safe_xack_propagates_redis_response_error() -> None:
    redis = MagicMock()
    redis.xack = AsyncMock(side_effect=ResponseError("NOGROUP No such key"))

    async def run() -> None:
        await _safe_xack(redis, "1-0")

    with pytest.raises(ResponseError):
        asyncio.run(run())


@pytest.mark.unit
def test_transient_retry_defers_xadd_until_after_backoff_task() -> None:
    """Backoff must not block _handle_one_delivery: XADD runs only after delayed task passes sleep."""
    job_id = "job_retry_async"
    correlation_id = "corr_retry_async"
    job_key = _job_key(job_id)
    blob_key = _blob_b64_key(job_id)
    pdf_b64 = base64.b64encode(b"%PDF-1.4 test").decode("ascii")

    async def mock_get(key: str) -> str | None:
        if key == job_key:
            return json.dumps({"job_id": job_id, "status": "queued", "reclaim_count": 0})
        if key == blob_key:
            return pdf_b64
        return None

    redis = MagicMock()
    redis.get = AsyncMock(side_effect=mock_get)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.xadd = AsyncMock(return_value="99-1")
    redis.xack = AsyncMock()

    sleep_entered = asyncio.Event()
    sleep_proceed = asyncio.Event()

    async def gated_sleep(_delay: float) -> None:
        sleep_entered.set()
        await sleep_proceed.wait()

    fields = {
        "job_id": job_id,
        "parser": "pypdf",
        "filename": "x.pdf",
        "language": "en",
        "attempt": "0",
        "correlation_id": correlation_id,
    }

    async def run() -> None:
        # Patch `_retry_backoff_sleep`, not `asyncio.sleep`: patching the stdlib attribute would
        # also affect `await asyncio.sleep(...)` in this test file and deadlock on `sleep_proceed`.
        with (
            patch("app.worker._retry_backoff_sleep", side_effect=gated_sleep),
            patch(
                "app.worker._process_pdf_bytes",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=503, detail="down"),
            ),
        ):
            await _handle_one_delivery(redis, "1-0", fields, source="new", consumer="test_consumer")
            assert redis.xadd.await_count == 0
            await asyncio.sleep(0)
            await asyncio.wait_for(sleep_entered.wait(), timeout=2.0)
            assert redis.xadd.await_count == 0
            sleep_proceed.set()
            await asyncio.sleep(0.05)
            assert redis.xadd.await_count == 1
            redis.xack.assert_awaited_once_with(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, "1-0")

    asyncio.run(run())
