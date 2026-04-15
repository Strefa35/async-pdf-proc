import asyncio
import base64
import json
import os
import random
import time
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.main import (
    JOB_TTL_SECONDS,
    LlmCapacityExceededError,
    REDIS_CONSUMER_GROUP,
    REDIS_STREAM_NAME,
    REDIS_URL,
    _blob_b64_key,
    _init_blocking_executors,
    _job_key,
    _process_pdf_bytes,
)
from app.worker_observability import (
    init_worker_metrics,
    log_json,
    metric_dlq,
    metric_done,
    metric_fail,
    metric_observe_duration,
    metric_retry,
    metric_skip_idempotent,
    observe_pending,
    span_worker_process,
)


REDIS_STREAM_DLQ = os.getenv("REDIS_STREAM_DLQ", "doc_jobs_dlq")
JOB_MAX_PROCESS_ATTEMPTS = max(1, int(os.getenv("JOB_MAX_PROCESS_ATTEMPTS", "5")))
JOB_MAX_RECLAIMS = max(0, int(os.getenv("JOB_MAX_RECLAIMS_PER_MESSAGE", "8")))
JOB_STREAM_CLAIM_IDLE_MS = max(
    1_000,
    int(os.getenv("JOB_STREAM_CLAIM_IDLE_MS", str(10 * 60 * 1000))),
)  # default 10 minutes
WORKER_XREAD_COUNT = max(1, int(os.getenv("WORKER_XREADGROUP_COUNT", "5")))
WORKER_XREAD_BLOCK_MS = max(100, int(os.getenv("WORKER_XREADGROUP_BLOCK_MS", "5000")))
WORKER_METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9464"))
JOB_RETRY_BASE_DELAY = max(0.05, float(os.getenv("JOB_RETRY_BASE_DELAY_SECONDS", "1")))

# Holds in-flight delayed retry tasks so they are not GC'd before completion (asyncio.create_task).
_retry_reenqueue_tasks: set[asyncio.Task[None]] = set()


def _decode_field(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _field_get(fields: dict[Any, Any], field_name: str) -> Any:
    if field_name in fields:
        return fields[field_name]
    bkey = field_name.encode("utf-8")
    return fields.get(bkey)


def _parse_int_field(val: Any, default: int) -> int:
    if val is None:
        return default
    try:
        return int(_decode_field(val))
    except (TypeError, ValueError):
        return default


def _backoff_seconds(attempt: int) -> float:
    # attempt is zero-based index of the delivery being retried (after failure)
    base = JOB_RETRY_BASE_DELAY * (2**attempt)
    cap = min(120.0, base)
    jitter = random.uniform(0, min(1.0, cap * 0.1))
    return cap + jitter


# Transient client / transport failures for Redis and similar I/O (matches retry policy).
_TRANSIENT_REDIS_CLIENT_EXC: tuple[type[BaseException], ...] = (
    RedisConnectionError,
    RedisTimeoutError,
    asyncio.TimeoutError,
    OSError,
    ConnectionError,
)


def classify_failure(exc: BaseException) -> tuple[bool, str]:
    if isinstance(exc, _TRANSIENT_REDIS_CLIENT_EXC):
        return True, type(exc).__name__
    if isinstance(exc, LlmCapacityExceededError):
        return True, "LlmCapacityExceededError"
    if isinstance(exc, HTTPException):
        if exc.status_code in (429, 502, 503, 504):
            return True, f"HTTPException:{exc.status_code}"
        return False, f"HTTPException:{exc.status_code}"
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError)):
        return True, type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        if exc.response.status_code in (429, 502, 503, 504):
            return True, f"HTTPStatusError:{exc.response.status_code}"
    return False, type(exc).__name__


def classify_job_failure(exc: BaseException) -> tuple[bool, str]:
    """Return (is_transient, reason_label) for worker retry / DLQ policy (tests)."""
    return classify_failure(exc)


async def _ensure_consumer_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, id="0-0", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" in str(e):
            return
        raise


async def _update_job_status(
    redis: Redis,
    job_id: str,
    *,
    status: str,
    result: Any = None,
    error: str | None = None,
    filename: str | None = None,
    parser: str | None = None,
    correlation_id: str | None = None,
    process_attempt: int | None = None,
    reclaim_count: int | None = None,
) -> None:
    raw = await redis.get(_job_key(job_id))
    job_data = json.loads(raw) if raw else {"job_id": job_id}

    job_data.update(
        {
            "status": status,
            "updated_at": int(time.time()),
            "result": result,
            "error": error,
        }
    )
    if filename is not None:
        job_data["filename"] = filename
    if parser is not None:
        job_data["parser"] = parser
    if correlation_id is not None:
        job_data["correlation_id"] = correlation_id
    if process_attempt is not None:
        job_data["process_attempt"] = process_attempt
    if reclaim_count is not None:
        job_data["reclaim_count"] = reclaim_count

    await redis.set(_job_key(job_id), json.dumps(job_data), ex=JOB_TTL_SECONDS)


async def _append_dlq(
    redis: Redis,
    *,
    job_id: str,
    error: str,
    reason: str,
    original_msg_id: str,
    attempt: int,
    reclaim_count: int,
    correlation_id: str,
    parser: str,
    filename: str,
    language: str,
) -> None:
    await redis.xadd(
        REDIS_STREAM_DLQ,
        {
            "job_id": job_id,
            "error": error[:4000],
            "reason": reason,
            "original_msg_id": original_msg_id,
            "attempt": str(attempt),
            "reclaim_count": str(reclaim_count),
            "correlation_id": correlation_id,
            "parser": parser,
            "filename": filename,
            "language": language,
            "failed_at": str(int(time.time())),
        },
    )


async def _safe_xack(redis: Redis, msg_id: str) -> None:
    try:
        await redis.xack(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, msg_id)
    except _TRANSIENT_REDIS_CLIENT_EXC:
        pass


async def _refresh_pending_metric(redis: Redis) -> None:
    try:
        info = await redis.xpending(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP)
        if isinstance(info, dict):
            observe_pending(REDIS_STREAM_NAME, float(info.get("pending", 0)))
        elif isinstance(info, (list, tuple)) and info:
            observe_pending(REDIS_STREAM_NAME, float(info[0]))
    except Exception:
        pass


async def _retry_backoff_sleep(seconds: float) -> None:
    """Backoff delay for delayed re-enqueue (separate from asyncio.sleep for narrow test patching)."""
    await asyncio.sleep(seconds)


async def _delayed_retry_reenqueue(
    redis: Redis,
    *,
    msg_id: str,
    delay: float,
    next_attempt: int,
    job_id: str,
    parser: str,
    filename: str,
    language: str,
    correlation_id: str,
    consumer: str,
) -> None:
    """Sleep off the consumer hot path, then XADD + XACK (same durability as inline sleep + xadd + ack)."""
    try:
        await _retry_backoff_sleep(delay)
        await redis.xadd(
            REDIS_STREAM_NAME,
            {
                "job_id": job_id,
                "parser": parser,
                "filename": filename,
                "language": language,
                "attempt": str(next_attempt),
                "correlation_id": correlation_id,
            },
        )
        metric_retry()
        await _safe_xack(redis, msg_id)
    except Exception as e:
        log_json(
            "job_retry_reenqueue_error",
            job_id=job_id,
            msg_id=msg_id,
            correlation_id=correlation_id,
            error=str(e),
            delay_seconds=delay,
            consumer=consumer,
        )


def _spawn_delayed_retry_reenqueue(
    redis: Redis,
    *,
    msg_id: str,
    delay: float,
    next_attempt: int,
    job_id: str,
    parser: str,
    filename: str,
    language: str,
    correlation_id: str,
    consumer: str,
) -> None:
    task = asyncio.create_task(
        _delayed_retry_reenqueue(
            redis,
            msg_id=msg_id,
            delay=delay,
            next_attempt=next_attempt,
            job_id=job_id,
            parser=parser,
            filename=filename,
            language=language,
            correlation_id=correlation_id,
            consumer=consumer,
        )
    )
    _retry_reenqueue_tasks.add(task)
    task.add_done_callback(_retry_reenqueue_tasks.discard)


async def _handle_one_delivery(
    redis: Redis,
    msg_id: str,
    fields: dict[Any, Any],
    *,
    source: Literal["new", "reclaim"],
    consumer: str,
) -> None:
    if not isinstance(fields, dict):
        fields = dict(fields)  # type: ignore[arg-type]

    job_id_val = _field_get(fields, "job_id")
    if job_id_val is None:
        log_json("malformed_stream_message", msg_id=msg_id, source=source, consumer=consumer)
        await _safe_xack(redis, msg_id)
        return

    job_id = _decode_field(job_id_val)
    parser = _decode_field(_field_get(fields, "parser")) if _field_get(fields, "parser") is not None else "pypdf"
    if parser not in (
        "pypdf",
        "gemini-2.5-flash",
        "gemini-2.5-flash-text",
        "gemini-2.5-flash-pdf",
        "mistral",
        "mistral-ocr",
    ):
        parser = "pypdf"
    filename = (
        _decode_field(_field_get(fields, "filename")) if _field_get(fields, "filename") is not None else "unknown.pdf"
    )
    language = _decode_field(_field_get(fields, "language")) if _field_get(fields, "language") is not None else "en"
    attempt = _parse_int_field(_field_get(fields, "attempt"), 0)
    correlation_id = (
        _decode_field(_field_get(fields, "correlation_id"))
        if _field_get(fields, "correlation_id") is not None
        else job_id
    )

    t0 = time.perf_counter()
    with span_worker_process(
        name="worker.process_doc_job",
        job_id=job_id,
        msg_id=msg_id,
        correlation_id=correlation_id,
    ):
        raw_job = await redis.get(_job_key(job_id))
        job_snapshot: dict[str, Any] = json.loads(raw_job) if raw_job else {}

        reclaim_count = int(job_snapshot.get("reclaim_count") or 0)
        if source == "reclaim":
            reclaim_count += 1
            if reclaim_count > JOB_MAX_RECLAIMS:
                err = f"Exceeded JOB_MAX_RECLAIMS_PER_MESSAGE ({JOB_MAX_RECLAIMS})"
                await _append_dlq(
                    redis,
                    job_id=job_id,
                    error=err,
                    reason="max_reclaims",
                    original_msg_id=msg_id,
                    attempt=attempt,
                    reclaim_count=reclaim_count,
                    correlation_id=correlation_id,
                    parser=parser,
                    filename=filename,
                    language=language,
                )
                metric_dlq()
                await _update_job_status(
                    redis,
                    job_id,
                    status="failed",
                    result=None,
                    error=err,
                    filename=filename,
                    parser=parser,
                    correlation_id=correlation_id,
                    process_attempt=attempt,
                    reclaim_count=reclaim_count,
                )
                metric_fail()
                log_json(
                    "job_dlq",
                    job_id=job_id,
                    msg_id=msg_id,
                    correlation_id=correlation_id,
                    reason="max_reclaims",
                    consumer=consumer,
                )
                await _safe_xack(redis, msg_id)
                metric_observe_duration(time.perf_counter() - t0)
                return

        if job_snapshot.get("status") == "done" and job_snapshot.get("result") is not None:
            metric_skip_idempotent()
            log_json(
                "job_skip_idempotent",
                job_id=job_id,
                msg_id=msg_id,
                correlation_id=correlation_id,
                source=source,
                consumer=consumer,
            )
            await _safe_xack(redis, msg_id)
            metric_observe_duration(time.perf_counter() - t0)
            return

        await _update_job_status(
            redis,
            job_id,
            status="processing",
            filename=filename,
            parser=parser,
            correlation_id=correlation_id,
            process_attempt=attempt,
            reclaim_count=reclaim_count,
        )

        try:
            blob_key = _blob_b64_key(job_id)
            pdf_b64 = await redis.get(blob_key)
            if not pdf_b64:
                raise RuntimeError("PDF blob not found in Redis")

            pdf_bytes = base64.b64decode(_decode_field(pdf_b64).encode("ascii"))

            parsed = await _process_pdf_bytes(
                pdf_bytes,
                filename=filename,
                parser=parser,  # type: ignore[arg-type]
                language=language,
                redis_client=redis,
            )

            await _update_job_status(
                redis,
                job_id,
                status="done",
                result=parsed,
                error=None,
                filename=filename,
                parser=parser,
                correlation_id=correlation_id,
                process_attempt=attempt,
                reclaim_count=reclaim_count,
            )
            await redis.delete(blob_key)
            metric_done()
            log_json(
                "job_done",
                job_id=job_id,
                msg_id=msg_id,
                correlation_id=correlation_id,
                parser=parser,
                consumer=consumer,
                source=source,
            )
            await _safe_xack(redis, msg_id)

        except Exception as e:
            transient, reason = classify_failure(e)
            log_json(
                "job_process_error",
                job_id=job_id,
                msg_id=msg_id,
                correlation_id=correlation_id,
                transient=transient,
                reason=reason,
                error=str(e),
                attempt=attempt,
                consumer=consumer,
                source=source,
            )

            next_attempt = attempt + 1
            if transient and next_attempt < JOB_MAX_PROCESS_ATTEMPTS:
                delay = _backoff_seconds(attempt)
                log_json(
                    "job_retry_scheduled",
                    job_id=job_id,
                    msg_id=msg_id,
                    correlation_id=correlation_id,
                    next_attempt=next_attempt,
                    delay_seconds=delay,
                    consumer=consumer,
                )
                _spawn_delayed_retry_reenqueue(
                    redis,
                    msg_id=msg_id,
                    delay=delay,
                    next_attempt=next_attempt,
                    job_id=job_id,
                    parser=parser,
                    filename=filename,
                    language=language,
                    correlation_id=correlation_id,
                    consumer=consumer,
                )
                metric_observe_duration(time.perf_counter() - t0)
                return
            elif transient:
                err = f"Max process attempts exceeded ({JOB_MAX_PROCESS_ATTEMPTS}): {e}"
                await _append_dlq(
                    redis,
                    job_id=job_id,
                    error=err,
                    reason="max_retries",
                    original_msg_id=msg_id,
                    attempt=attempt,
                    reclaim_count=reclaim_count,
                    correlation_id=correlation_id,
                    parser=parser,
                    filename=filename,
                    language=language,
                )
                metric_dlq()
                await _update_job_status(
                    redis,
                    job_id,
                    status="failed",
                    result=None,
                    error=err,
                    filename=filename,
                    parser=parser,
                    correlation_id=correlation_id,
                    process_attempt=attempt,
                    reclaim_count=reclaim_count,
                )
                metric_fail()
                log_json(
                    "job_dlq",
                    job_id=job_id,
                    msg_id=msg_id,
                    correlation_id=correlation_id,
                    reason="max_retries",
                    consumer=consumer,
                )
                await _safe_xack(redis, msg_id)
            else:
                await _update_job_status(
                    redis,
                    job_id,
                    status="failed",
                    result=None,
                    error=str(e),
                    filename=filename,
                    parser=parser,
                    correlation_id=correlation_id,
                    process_attempt=attempt,
                    reclaim_count=reclaim_count,
                )
                metric_fail()
                await _safe_xack(redis, msg_id)

        metric_observe_duration(time.perf_counter() - t0)


async def _drain_autoclaim(redis: Redis, *, consumer: str) -> None:
    """Pick up stale pending messages (PR-TR-8)."""
    try:
        resp = await redis.xautoclaim(
            REDIS_STREAM_NAME,
            REDIS_CONSUMER_GROUP,
            consumer,
            min_idle_time=JOB_STREAM_CLAIM_IDLE_MS,
            start_id="0-0",
            count=WORKER_XREAD_COUNT,
        )
    except Exception as e:
        log_json("xautoclaim_error", error=str(e), consumer=consumer)
        return

    # redis-py: [next_start_id, [[msg_id, {fields}], ...]]
    if not resp or len(resp) < 2:
        return
    _next_id, messages = resp[0], resp[1]
    if not messages:
        return
    for item in messages:
        if not item:
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            msg_id, raw_fields = item[0], item[1]
        else:
            continue
        fields: dict[Any, Any] = dict(raw_fields) if not isinstance(raw_fields, dict) else raw_fields
        await _handle_one_delivery(redis, str(msg_id), fields, source="reclaim", consumer=consumer)


async def main() -> None:
    _init_blocking_executors()
    init_worker_metrics(WORKER_METRICS_PORT)

    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    await redis.ping()
    await _ensure_consumer_group(redis)

    consumer = os.getenv("REDIS_CONSUMER_NAME", os.uname().nodename)

    while True:
        await _refresh_pending_metric(redis)
        await _drain_autoclaim(redis, consumer=consumer)

        streams = {REDIS_STREAM_NAME: ">"}
        try:
            resp = await redis.xreadgroup(
                groupname=REDIS_CONSUMER_GROUP,
                consumername=consumer,
                streams=streams,
                count=WORKER_XREAD_COUNT,
                block=WORKER_XREAD_BLOCK_MS,
            )
        except RedisConnectionError:
            try:
                await redis.aclose()
            except Exception:
                pass
            redis = Redis.from_url(REDIS_URL, decode_responses=True)
            await redis.ping()
            await _ensure_consumer_group(redis)
            await asyncio.sleep(1)
            continue
        except Exception:
            await asyncio.sleep(1)
            continue
        if not resp:
            continue

        for _, messages in resp:
            for msg_id, fields in messages:
                await _handle_one_delivery(redis, str(msg_id), fields, source="new", consumer=consumer)


if __name__ == "__main__":
    asyncio.run(main())