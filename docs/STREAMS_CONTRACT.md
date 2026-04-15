# Redis Streams job contract (`doc_jobs`)

This document defines how the async PDF worker consumes `doc_jobs` (and related streams). It satisfies backlog item **PR-TR-6** and informs **PR-TR-7–PR-TR-9**, **PR-TR-17**, and **PR-TR-18**.

## Delivery semantics

- The primary queue uses a **consumer group** on stream `doc_jobs` (configurable via `REDIS_STREAM_NAME` / `REDIS_CONSUMER_GROUP`).
- Redis Streams consumer groups provide **at-least-once** delivery: a message stays in the **pending entries list (PEL)** of the assigned consumer until **`XACK`** removes it.
- The worker therefore **must be idempotent** for a given `job_id`: duplicate deliveries (retries, reclaim after crash, or horizontal scale) may run the same logical job more than once.

## Idempotent job execution

- Canonical job state lives in Redis key `doc:job:{job_id}` (JSON).
- Before expensive work, the worker checks this record. If `status` is already **`done`** and `result` is present, the handler **skips processing**, emits a structured log event, and **`XACK`s** the stream message.
- PDF parsing uses content-addressed cache keys (`pdf:{parser}:{sha256}`), so re-processing the same bytes is safe and mostly cache-backed.

## When `XACK` is allowed

The worker **`XACK`s** the primary stream message ID only after one of the following terminal outcomes:

1. **Success** — Job updated to `done`, PDF blob key removed, message **`XACK`ed**.
2. **Terminal failure (no further retry)** — Job updated to `failed` (or moved to DLQ first, see below), message **`XACK`ed**.
3. **Malformed message** — Missing `job_id` (cannot correlate work): message **`XACK`ed** (optionally mirrored to DLQ with diagnostics).
4. **Retry re-enqueue** — For a **transient** failure with attempts remaining: after **exponential backoff + jitter**, a **new** message is **`XADD`ed** to `doc_jobs` with an incremented `attempt` field, then the **current** message is **`XACK`ed** (ordering: `XADD` then `XACK` so a crash after `XADD` may duplicate work but idempotency covers it). The backoff and subsequent **`XADD` / `XACK`** run in a **background asyncio task** so the main **`XREADGROUP`** loop can process other deliveries during the wait; the stream message stays **pending** until that task completes **`XADD`** then **`XACK`** (same durability as an inline sleep before re-enqueue).
5. **Dead-letter** — After max process attempts or max reclaim attempts: payload and error metadata are **`XADD`ed** to the DLQ stream (default `doc_jobs_dlq`), job marked `failed`, primary message **`XACK`ed**.

The worker does **not** `XACK` while a message should remain pending for automatic reclaim (see visibility timeout). Normal processing either completes the outcomes above or, on shutdown mid-flight, leaves the message pending for **`XAUTOCLAIM`**.

## Retries (PR-TR-7)

- Transient classes include: Redis connection errors, HTTP `502`/`503`/`504`/`429` from providers, LLM capacity saturation (`LlmCapacityExceededError`), and asyncio timeouts around blocking work.
- Bounded **`attempt`** (integer) is carried on stream fields and mirrored into the job record. Backoff (`JOB_RETRY_BASE_DELAY_SECONDS`, exponential cap + jitter) is applied in the delayed re-enqueue path **before** the retry `XADD` (see **When `XACK` is allowed**, item 4 above).
- Non-transient errors (e.g. HTTP `400`, missing PDF blob, configuration errors) do not increment retry; they fail the job immediately.

## Pending reclaim (PR-TR-8)

- Messages left pending longer than **`JOB_STREAM_CLAIM_IDLE_MS`** (default several minutes) may be **`XAUTOCLAIM`ed** by an active consumer.
- Each reclaim increments **`reclaim_count`** on the job record. If **`JOB_MAX_RECLAIMS_PER_MESSAGE`** is exceeded, the message is treated as poison/stuck and sent to **DLQ** with reason `max_reclaims`, then **`XACK`ed**.

## Dead-letter queue (PR-TR-9)

- DLQ stream name defaults to **`doc_jobs_dlq`** (`REDIS_STREAM_DLQ`).
- DLQ entries are plain stream fields (JSON-serialized where needed): `job_id`, `error`, `reason`, `original_msg_id`, `attempt`, `reclaim_count`, `correlation_id`, `failed_at`, optional `parser` / `filename`.
- **Replay policy:** Operations may **`XREAD`** from `doc_jobs_dlq`, inspect/fix the underlying job or payload, then **`XADD`** a fresh job message to `doc_jobs` with `attempt=0` and a new `correlation_id` (or reuse for audit). There is no automatic replay in the application.

## Horizontal scale (PR-TR-18)

- Run **multiple worker containers** against the same `REDIS_CONSUMER_GROUP` (e.g. `docker compose up --scale worker=3`). Redis assigns pending messages across consumers.
- Tune **`WORKER_XREADGROUP_COUNT`** and **`WORKER_XREADGROUP_BLOCK_MS`** for batching vs latency.
- Idempotency (above) is required so that duplicate or overlapping deliveries never corrupt user-visible results.

## Correlation, metrics, tracing

- **`correlation_id`** is assigned at enqueue time and propagated on stream fields, job JSON, structured logs, and optional OpenTelemetry spans (**PR-TR-10–PR-TR-12**).
- Prometheus metrics are exposed from the worker on **`WORKER_METRICS_PORT`** (default `9464`; set to `0` to disable). See `README.md` / `.env.example`.
- OpenTelemetry OTLP export is **optional** in the worker: set `OTEL_EXPORTER_OTLP_ENDPOINT` (and standard OTEL resource attributes) when an OTLP collector is available. The API assigns `correlation_id` at enqueue for log/trace correlation even when OTLP is disabled in the backend process.
