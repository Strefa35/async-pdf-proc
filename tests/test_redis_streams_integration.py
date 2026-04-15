"""
Redis Streams integration tests (PR-TR-14).

Uses Testcontainers to run Redis 7.x with consumer groups, mirroring the app's
`doc_jobs` / `doc_workers` pattern. Requires a working Docker daemon unless skipped.

Skip entirely: ``SKIP_STREAMS_TESTS=1`` or ``pytest -m "not streams"``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from redis.asyncio import Redis

pytestmark = [
    pytest.mark.streams,
    pytest.mark.filterwarnings(
        "ignore:The @wait_container_is_ready decorator is deprecated.*:DeprecationWarning"
    ),
]

STREAM = "tc_pr_tr14_doc_jobs"
GROUP = "tc_pr_tr14_workers"
DLQ = "tc_pr_tr14_doc_jobs_dlq"


def _pending_count(info: Any) -> int:
    if isinstance(info, dict):
        return int(info.get("pending", 0))
    if isinstance(info, (list, tuple)) and info:
        return int(info[0])
    return 0


@pytest.fixture(scope="module")
def redis_url() -> str:
    if os.environ.get("SKIP_STREAMS_TESTS", "").strip().lower() in ("1", "true", "yes"):
        pytest.skip("SKIP_STREAMS_TESTS is set")
    try:
        from testcontainers.redis import RedisContainer
    except ImportError as e:  # pragma: no cover
        pytest.skip(f"testcontainers not available: {e}")

    with RedisContainer("redis:7.2-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        pwd = container.password
        if pwd:
            yield f"redis://:{pwd}@{host}:{port}/0"
        else:
            yield f"redis://{host}:{port}/0"


def test_consumer_group_create_read_ack(redis_url: str) -> None:
    """Happy path: XGROUP CREATE, XADD, XREADGROUP, XACK; PEL is empty."""

    async def _run() -> None:
        r = Redis.from_url(redis_url, decode_responses=True)
        try:
            await r.delete(STREAM)
            await r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
            msg_id = await r.xadd(
                STREAM,
                {
                    "job_id": "job_happy",
                    "parser": "pypdf",
                    "filename": "a.pdf",
                    "language": "en",
                    "attempt": "0",
                    "correlation_id": "corr_happy",
                },
            )
            resp = await r.xreadgroup(GROUP, "consumer_a", streams={STREAM: ">"}, count=1, block=2000)
            assert resp
            _stream_name, messages = resp[0]
            assert len(messages) == 1
            read_id, fields = messages[0]
            assert read_id == msg_id
            assert fields.get("job_id") == "job_happy"

            await r.xack(STREAM, GROUP, msg_id)
            pend = await r.xpending(STREAM, GROUP)
            assert _pending_count(pend) == 0
        finally:
            await r.aclose()

    asyncio.run(_run())


def test_stale_pending_message_xautoclaimed(redis_url: str) -> None:
    """Failure / recovery path: pending without XACK becomes eligible for XAUTOCLAIM."""

    async def _run() -> None:
        r = Redis.from_url(redis_url, decode_responses=True)
        try:
            await r.delete(STREAM)
            await r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
            msg_id = await r.xadd(STREAM, {"job_id": "job_stale", "attempt": "0", "correlation_id": "c_stale"})

            await r.xreadgroup(GROUP, "consumer_first", streams={STREAM: ">"}, count=1, block=2000)
            pend = await r.xpending(STREAM, GROUP)
            assert _pending_count(pend) == 1

            await asyncio.sleep(0.15)
            ac = await r.xautoclaim(STREAM, GROUP, "consumer_second", min_idle_time=1, start_id="0-0", count=10)
            assert ac is not None and len(ac) >= 2
            claimed_messages = ac[1]
            assert claimed_messages, f"expected claimed messages, got {ac!r}"
            cid, fields = claimed_messages[0]
            assert cid == msg_id
            assert fields.get("job_id") == "job_stale"

            await r.xack(STREAM, GROUP, msg_id)
            pend2 = await r.xpending(STREAM, GROUP)
            assert _pending_count(pend2) == 0
        finally:
            await r.aclose()

    asyncio.run(_run())


def test_dlq_stream_append_and_primary_ack(redis_url: str) -> None:
    """Simulated terminal failure: mirror DLQ + XACK primary (no app process)."""

    async def _run() -> None:
        r = Redis.from_url(redis_url, decode_responses=True)
        try:
            await r.delete(STREAM, DLQ)
            await r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
            msg_id = await r.xadd(STREAM, {"job_id": "job_dlq", "attempt": "4", "correlation_id": "c_dlq"})

            await r.xreadgroup(GROUP, "consumer_x", streams={STREAM: ">"}, count=1, block=2000)

            await r.xadd(
                DLQ,
                {
                    "job_id": "job_dlq",
                    "error": "max_retries exceeded (test)",
                    "reason": "max_retries",
                    "original_msg_id": msg_id,
                    "attempt": "4",
                    "correlation_id": "c_dlq",
                    "failed_at": "1",
                },
            )
            await r.xack(STREAM, GROUP, msg_id)

            pend = await r.xpending(STREAM, GROUP)
            assert _pending_count(pend) == 0

            dlq_len = await r.xlen(DLQ)
            assert dlq_len == 1
        finally:
            await r.aclose()

    asyncio.run(_run())


def test_busygroup_on_duplicate_create_is_idempotent_pattern(redis_url: str) -> None:
    """Worker-style group creation: BUSYGROUP is ignored when the group already exists."""

    async def _run() -> None:
        r = Redis.from_url(redis_url, decode_responses=True)
        try:
            await r.delete(STREAM)
            await r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
            try:
                await r.xgroup_create(STREAM, GROUP, id="0-0", mkstream=True)
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    raise
            else:  # pragma: no cover
                pytest.fail("expected BUSYGROUP on duplicate xgroup_create")
        finally:
            await r.aclose()

    asyncio.run(_run())
