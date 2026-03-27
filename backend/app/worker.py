import asyncio
import base64
import json
import os
import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.main import (
    JOB_TTL_SECONDS,
    ParserType,
    REDIS_CONSUMER_GROUP,
    REDIS_STREAM_NAME,
    REDIS_URL,
    _blob_b64_key,
    _job_key,
    _process_pdf_bytes,
)


def _decode_field(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


async def _ensure_consumer_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, id="0-0", mkstream=True)
    except Exception as e:
        # BUSYGROUP means the group already exists.
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

    await redis.set(_job_key(job_id), json.dumps(job_data), ex=JOB_TTL_SECONDS)


async def main() -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    await redis.ping()
    await _ensure_consumer_group(redis)

    consumer = os.getenv("REDIS_CONSUMER_NAME", os.uname().nodename)

    while True:
        streams = {REDIS_STREAM_NAME: ">"}
        try:
            resp = await redis.xreadgroup(
                groupname=REDIS_CONSUMER_GROUP,
                consumername=consumer,
                streams=streams,
                count=5,
                block=5000,
            )
        except RedisConnectionError:
            # Redis can temporarily close connections during container restarts.
            # Reconnect and resume consuming without killing the worker.
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
                # Redis Streams message fields can come back with bytes or str keys
                # depending on `decode_responses` and redis-py internals.
                if not isinstance(fields, dict):
                    fields = dict(fields)  # type: ignore[arg-type]

                def get_field(field_name: str) -> Any:
                    if field_name in fields:
                        return fields[field_name]
                    bkey = field_name.encode("utf-8")
                    return fields.get(bkey)

                job_id_val = get_field("job_id")
                parser_val = get_field("parser")
                filename_val = get_field("filename")
                language_val = get_field("language")

                if job_id_val is None:
                    # Skip malformed message (ack in finally).
                    await redis.xack(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, msg_id)
                    continue

                job_id = _decode_field(job_id_val)
                parser = _decode_field(parser_val) if parser_val is not None else "pypdf"
                if parser not in ("pypdf", "gemini-2.5-flash", "mistral"):
                    parser = "pypdf"
                filename = _decode_field(filename_val) if filename_val is not None else "unknown.pdf"
                language = _decode_field(language_val) if language_val is not None else "en"

                try:
                    await _update_job_status(redis, job_id, status="processing", filename=filename, parser=parser)

                    blob_key = _blob_b64_key(job_id)
                    pdf_b64 = await redis.get(blob_key)
                    if not pdf_b64:
                        raise RuntimeError("PDF blob not found in Redis")
                    pdf_bytes = base64.b64decode(pdf_b64.encode("ascii"))

                    # Process and reuse Redis cache
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
                    )
                    await redis.delete(blob_key)
                except Exception as e:
                    await _update_job_status(
                        redis,
                        job_id,
                        status="failed",
                        result=None,
                        error=str(e),
                        filename=filename,
                        parser=parser,
                    )
                finally:
                    try:
                        await redis.xack(REDIS_STREAM_NAME, REDIS_CONSUMER_GROUP, msg_id)
                    except RedisConnectionError:
                        # If the connection is already gone, we can't ACK. The message
                        # will be retried by the group.
                        pass


if __name__ == "__main__":
    asyncio.run(main())

